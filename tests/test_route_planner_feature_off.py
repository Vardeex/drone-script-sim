"""Testy: planer da się wyłączyć w ``config.json`` i działa bez funkcji przeszkód."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.server import app

ROUTE = {
    "format": "dronesim-route", "version": 1, "mode": "simple",
    "default_speed": 50, "start_yaw_deg": 0, "return_home": False,
    "points": [{"x": 100, "y": 0, "z": 100, "heading": "track", "yaw_deg": 0,
                "hover_s": 0, "speed": None}],
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _reload_with(monkeypatch, tmp_path, payload: dict):
    """Udawaj restart aplikacji z podanym ``config.json``."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DRONESIM_CONFIG_FILE", str(config_file))
    import app.server as server
    return importlib.reload(server)


def test_table_without_obstacles(monkeypatch, tmp_path):
    """Planer działa, gdy funkcja przeszkód jest wyłączona (bez kontroli kolizji)."""
    module = _reload_with(
        monkeypatch, tmp_path, {"features": {"obstacles": {"enabled": False}}})
    try:
        with TestClient(module.app) as client:
            info = client.get("/api/route_planner/info").json()
            assert info["collision_check"] is False
            report = client.post("/api/route_planner/validate",
                                 json={"route": ROUTE}).json()
            assert report["collisions"] is None
            assert report["errors"] == 0, report["problems"]
            code = client.post("/api/route_planner/code",
                               json={"route": ROUTE}).json()
            assert code["code"]
    finally:
        monkeypatch.undo()
        importlib.reload(module)


def test_planner_disabled_in_config(monkeypatch, tmp_path):
    """Wyłączony planer nie ma routera, a aplikacja działa normalnie."""
    module = _reload_with(
        monkeypatch, tmp_path, {"features": {"route_planner": {"enabled": False}}})
    try:
        with TestClient(module.app) as client:
            ids = [f["id"] for f in client.get("/api/features").json()]
            assert "route_planner" not in ids, ids
            assert client.get("/api/route_planner/info").status_code == 404
            assert client.get("/api/health").text == "ok"
            started = client.post("/api/run",
                                  json={"source": "print('ok')", "save": False})
            assert started.status_code == 200
    finally:
        monkeypatch.undo()
        importlib.reload(module)


def test_collisions_used_when_obstacles_enabled(client):
    """Z włączonymi przeszkodami trasa przez bryłę daje kolizję."""
    scene = {"obstacles": [{"kind": "box", "position": [100, 0, 80],
                            "size": [100, 100, 100], "yaw": 0}]}
    report = client.post("/api/route_planner/validate",
                         json={"route": ROUTE, "scene": scene}).json()
    if report["collisions"] is None:
        pytest.skip("funkcja przeszkód wyłączona w tej konfiguracji")
    assert report["collisions"], report
