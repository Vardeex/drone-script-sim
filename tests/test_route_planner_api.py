"""Testy API planera trasy (``/api/route_planner``)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def route(*points, **options):
    """Trasa w formacie JSON planera; punkty jako ``(x, y, z)`` w cm."""
    base = {"format": "dronesim-route", "version": 1, "mode": "simple",
            "default_speed": 50, "start_yaw_deg": 0, "return_home": False,
            "points": [{"x": x, "y": y, "z": z, "heading": "track", "yaw_deg": 0,
                        "hover_s": 0, "speed": None} for x, y, z in points]}
    base.update(options)
    return base


def test_info_reports_limits_and_modes(client):
    data = client.get("/api/route_planner/info").json()
    assert data["id"] == "route_planner"
    assert {m["id"] for m in data["modes"]} == {"simple", "smooth"}
    limits = data["limits"]
    # limity z modelu planera: ruch 20-500 cm, prędkość 10-100 cm/s, wysokość 10-500 cm
    assert (limits["min_move_cm"], limits["max_move_cm"]) == (20, 500)
    assert (limits["min_speed_cms"], limits["max_speed_cms"]) == (10, 100)
    assert (limits["min_height_cm"], limits["max_height_cm"]) == (10, 500)


def test_validate_flags_short_leg_and_bad_height(client):
    """Odcinek 10 cm < 20 cm (Tello łączy ruchy) i wysokość 600 cm > 500 cm."""
    data = client.post("/api/route_planner/validate",
                       json={"route": route((100, 0, 600), (110, 0, 600))}).json()
    messages = " ".join(p["message"] for p in data["problems"])
    assert data["errors"] >= 1, data["problems"]
    assert "600" in messages or "wysoko" in messages.lower(), messages


def test_validate_accepts_proper_route(client):
    data = client.post("/api/route_planner/validate",
                       json={"route": route((100, 0, 100), (200, 0, 100))}).json()
    assert data["errors"] == 0, data["problems"]
    # tor zaczyna się w punkcie startu (0, 0) na wysokości takeoff 80 cm,
    # potem 100 cm do punktu 1 (z 80 -> 100 = 20 cm) i 100 cm do punktu 2:
    # dystans = 100,2 + 100 ≈ 202 cm (patrz zmierzona odpowiedź)
    assert data["stats"]["distance_cm"] == pytest.approx(202, abs=2)
    assert data["stats"]["legs_cm"][1] == pytest.approx(100, abs=1)


def test_preview_returns_track_and_stats(client):
    data = client.post("/api/route_planner/preview",
                       json={"route": route((100, 0, 100), (200, 0, 100))}).json()
    # punkty: start (0,0,80) + dwa punkty trasy
    assert len(data["points"]) == 3
    assert data["points"][0]["label"] == "start"
    assert data["distance_cm"] == pytest.approx(202, abs=2)
    # 202 cm przy 50 cm/s -> ok. 4 s samego przelotu; z rozbiegiem i zawisem
    # na starcie planer daje 15,9 s (zmierzone) - sprawdzamy rząd wielkości
    assert 10 < data["eta_s"] < 30
    assert data["battery_pct"] > 0


def test_code_simple_uses_go_xyz_speed_and_route_block(client):
    data = client.post("/api/route_planner/code",
                       json={"route": route((100, 0, 100), (200, 0, 100)),
                             "mode": "simple"}).json()
    code = data["code"]
    assert "go_xyz_speed" in code
    assert "dronesim-route" in code          # blok-znacznik do wczytania trasy
    assert data["mode"] == "simple"


def test_code_smooth_uses_pilot_path(client):
    data = client.post("/api/route_planner/code",
                       json={"route": route((100, 0, 100), (200, 0, 100)),
                             "mode": "smooth"}).json()
    assert "pilot.path(" in data["code"]


def test_code_rejects_unknown_mode(client):
    response = client.post("/api/route_planner/code",
                           json={"route": route((100, 0, 100), (200, 0, 100)),
                                 "mode": "turbo"})
    assert response.status_code == 400


def test_load_roundtrip(client):
    """Kod wygenerowany przez planer da się wczytać z powrotem do trasy."""
    original = route((100, 0, 100), (200, 50, 120), mode="simple")
    code = client.post("/api/route_planner/code",
                       json={"route": original}).json()["code"]
    loaded = client.post("/api/route_planner/load", json={"source": code}).json()
    assert loaded["route"]["mode"] == original["mode"]
    assert len(loaded["route"]["points"]) == 2
    first = loaded["route"]["points"][0]
    assert first["x"] == pytest.approx(100, abs=1)
    assert first["z"] == pytest.approx(100, abs=1)


def test_load_refuses_foreign_script(client):
    response = client.post("/api/route_planner/load",
                           json={"source": "from djitellopy import Tello\n"})
    assert response.status_code == 400
    assert "trasy" in response.json()["detail"].lower()


def test_invalid_route_returns_400(client):
    broken = route((100, 0, 100))
    broken["points"][0]["heading"] = "na ksiezyc"
    response = client.post("/api/route_planner/validate", json={"route": broken})
    assert response.status_code == 400
