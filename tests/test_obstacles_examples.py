"""Testy scenariuszy z `examples/`: slalom z bramkami (demo + kolizja).

Sprawdzają pełną ścieżkę: uruchomienie skryptu z opcją `obstacles`,
analiza lotu po symulacji, zapis sceny razem z lotem i wczytanie z historii.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import paths
from app.features.obstacles import store
from app.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def scenes_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Przykładowe sceny z repo + katalog użytkownika w tmp."""
    root = tmp_path / "scenes"
    (root / store.USER_DIR_NAME).mkdir(parents=True)
    for file in (paths.PROJECT_ROOT / "scenes").glob("*.json"):
        (root / file.name).write_text(file.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(store, "SCENES_DIR", root)
    return root


def _run_example(client, name: str, scene: dict, margin: int = 20) -> dict:
    source = (paths.EXAMPLES_DIR / f"{name}.py").read_text(encoding="utf-8")
    started = client.post("/api/run", json={
        "source": source, "script_name": f"{name}.py",
        "options": {"obstacles": {"scene": scene, "margin_cm": margin}},
    })
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        data = client.get(f"/api/run/live/{run_id}").json()
        if data["status"] != "running":
            assert data["status"] == "done", data.get("error")
            return data["flight"]
        time.sleep(0.05)
    raise AssertionError("Skrypt nie zakończył się w czasie.")


def test_slalom_demo_passes_all_gates(client, scenes_tmp: Path):
    scene = client.get("/api/obstacles/scenes/gate_slalom").json()
    flight = _run_example(client, "obstacles_demo", scene)
    try:
        report = flight["obstacles"]
        assert report["stats"]["gates_total"] == 3
        assert report["stats"]["gates_passed"] == 3, report["findings"]
        assert report["stats"]["collisions"] == 0
        # cały slalom trzyma dystans od belek ramy - ani jednego zbliżenia
        assert report["stats"]["warnings"] == 0, report["findings"]
        assert report["stats"]["min_distance_cm"] >= 20.0
        assert flight["scene"]["name"] == scene["name"]
    finally:
        client.delete(f"/api/flights/{flight['id']}")


def test_slalom_crash_hits_gate_frame(client, scenes_tmp: Path):
    scene = client.get("/api/obstacles/scenes/gate_slalom").json()
    flight = _run_example(client, "obstacles_crash", scene)
    try:
        report = flight["obstacles"]
        collisions = [f for f in report["findings"] if f["level"] == "collision"]
        assert len(collisions) == 1, report["findings"]
        assert "Bramka 2" in collisions[0]["message"]
        # kolizja ma przypisaną linię skryptu (skąd przyleciał dron)
        assert collisions[0]["line"] is not None
        assert report["stats"]["gates_passed"] == 1
    finally:
        client.delete(f"/api/flights/{flight['id']}")


def test_history_flight_has_its_own_scene(client, scenes_tmp: Path):
    scene = client.get("/api/obstacles/scenes/gate_slalom").json()
    flight = _run_example(client, "obstacles_crash", scene)
    stored = client.get(f"/api/flights/{flight['id']}").json()
    try:
        assert stored["scene"]["obstacles"] == scene["obstacles"]
        assert stored["obstacles"]["scene"]["name"] == scene["name"]
        assert stored["obstacles"]["stats"]["collisions"] == 1
        history = client.get("/api/flights").json()
        entry = next(item for item in history if item["id"] == flight["id"])
        assert entry["script_name"] == "obstacles_crash.py"
    finally:
        client.delete(f"/api/flights/{flight['id']}")
