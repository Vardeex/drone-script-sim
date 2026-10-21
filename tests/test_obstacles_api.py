"""Testy API funkcji ``obstacles`` i zapisu sceny razem z lotem."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.features.obstacles import store
from app.features.obstacles.model import Obstacle, Scene
from app.server import app

FLY_THROUGH = """
from djitellopy import Tello

t = Tello()
t.connect()
t.takeoff()
t.move_forward(300)
t.land()
"""


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def scenes_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "scenes"
    (root / store.USER_DIR_NAME).mkdir(parents=True)
    monkeypatch.setattr(store, "SCENES_DIR", root)
    return root


def _wait(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/run/live/{run_id}").json()
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError("Uruchomienie nie zakończyło się w czasie.")


def _scene_with_wall() -> dict:
    return Scene(name="Test", obstacles=[
        Obstacle(kind="box", name="ściana", position=(150, 0, 200), size=(10, 400, 400)),
    ]).as_dict()


def test_info_and_empty_scene(client):
    info = client.get("/api/obstacles/info").json()
    assert [k["id"] for k in info["kinds"]] == ["box", "cylinder", "gate", "plane"]
    assert info["drone_size_cm"] == [10.0, 10.0, 5.0]
    empty = client.post("/api/obstacles/scene/empty").json()
    assert empty["obstacles"] == []
    assert empty["room"] == [400.0, 400.0, 250.0]
    preset = client.get("/api/obstacles/presets/gate").json()
    assert preset["kind"] == "gate" and preset["opening"] == [60.0, 60.0]


def test_scene_api_save_load_delete(client, scenes_tmp: Path):
    scene = _scene_with_wall()
    saved = client.post("/api/obstacles/scenes/moj-tor", json={"scene": scene})
    assert saved.status_code == 200, saved.text
    assert saved.json()["user"] is True

    loaded = client.get("/api/obstacles/scenes/moj-tor").json()
    assert loaded["name"] == "Test"
    assert loaded["obstacles"][0]["name"] == "ściana"

    names = [s["name"] for s in client.get("/api/obstacles/scenes").json()]
    assert "moj-tor" in names
    assert client.delete("/api/obstacles/scenes/moj-tor").status_code == 200
    assert client.get("/api/obstacles/scenes/moj-tor").status_code == 404


def test_scene_api_rejects_bad_payload(client, scenes_tmp: Path):
    response = client.post("/api/obstacles/scenes/zle",
                           json={"scene": {"obstacles": [{"kind": "kula"}]}})
    assert response.status_code == 400
    assert client.get("/api/obstacles/scenes/..%2Fetc").status_code in (400, 404)


def test_analyse_endpoint(client):
    body = {
        "scene": _scene_with_wall(),
        "samples": [{"t": 0.0, "x": 0.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
                    {"t": 2.0, "x": 300.0, "y": 0.0, "z": 80.0, "yaw": 0.0}],
        "margin_cm": 20,
    }
    report = client.post("/api/obstacles/analyse", json=body).json()
    assert report["stats"]["collisions"] == 1


def test_flight_saves_scene_and_report(client, scenes_tmp: Path):
    scene = _scene_with_wall()
    started = client.post("/api/run", json={
        "source": FLY_THROUGH, "script_name": "sciana.py",
        "options": {"obstacles": {"scene": scene, "margin_cm": 20}},
    })
    result = _wait(client, started.json()["id"])
    flight = result["flight"]
    assert flight["scene"]["obstacles"][0]["name"] == "ściana"
    assert flight["obstacles"]["stats"]["collisions"] == 1
    # historia: ten sam lot (wczytany z pliku) ma tę samą scenę i raport
    stored = client.get(f"/api/flights/{flight['id']}").json()
    assert stored["scene"] == scene
    assert stored["obstacles"]["stats"]["collisions"] == 1
    client.delete(f"/api/flights/{flight['id']}")


def test_flight_without_scene_has_no_report(client, scenes_tmp: Path):
    started = client.post("/api/run", json={"source": FLY_THROUGH, "script_name": "brak.py"})
    flight = _wait(client, started.json()["id"])["flight"]
    assert flight.get("obstacles") is None
    client.delete(f"/api/flights/{flight['id']}")


def test_post_save_hook_failure_does_not_break_save(monkeypatch):
    from app.sim.core import FlightData

    def boom(payload, options):
        raise RuntimeError("awaria dodatku")

    storage.register_post_save_hook(boom)
    try:
        payload = storage.save(FlightData(script_name="x.py"))
    finally:
        storage.POST_SAVE_HOOKS.remove(boom)
    assert payload["id"]
    assert storage.load(payload["id"]) is not None
    storage.delete(payload["id"])
