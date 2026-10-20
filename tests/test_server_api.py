"""Testy API serwera FastAPI (uruchamianie skryptów, loty, CSV, import)."""

from __future__ import annotations

import os
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import runner
from app.server import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _wait(client, run_id, timeout=30.0):
    """Poczekaj na zakończenie uruchomienia (polling jak w UI)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/run/live/{run_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise AssertionError("Uruchomienie nie zakończyło się w czasie.")


SQUARE = """
from djitellopy import Tello

t = Tello()
t.connect()
t.takeoff()
for _ in range(4):
    t.move_forward(100)
    t.rotate_clockwise(90)
t.land()
"""


def test_health_and_index(client):
    assert client.get("/api/health").text == "ok"
    assert client.get("/").status_code == 200


def test_adapters_endpoint(client):
    data = client.get("/api/adapters").json()
    ids = [a["id"] for a in data]
    assert "tello" in ids
    tello = next(a for a in data if a["id"] == "tello")
    assert tello["modules"] == ["djitellopy"]
    assert tello["limits"]["move_max_cm"] == 500


def test_examples_endpoint(client):
    assert isinstance(client.get("/api/examples").json(), list)


def test_run_script_saves_flight_and_history(client):
    response = client.post("/api/run", json={"source": SQUARE, "script_name": "kwadrat.py"})
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "running" and run["adapter"] == "tello"

    result = _wait(client, run["id"])
    assert result["status"] == "done", result.get("error")
    flight = result["flight"]
    assert flight["script_name"] == "kwadrat.py"
    assert flight["status"] == "ok"
    assert flight["stats"]["distance_cm"] == pytest.approx(400.0, abs=1.0)
    assert flight["samples"] and flight["events"]

    history = client.get("/api/flights").json()
    assert any(item["id"] == flight["id"] for item in history)

    stored = client.get(f"/api/flights/{flight['id']}")
    assert stored.status_code == 200
    assert stored.json()["id"] == flight["id"]


def test_run_without_save(client):
    response = client.post("/api/run", json={"source": "print('hi')", "save": False})
    result = _wait(client, response.json()["id"])
    assert result["status"] == "done"
    assert result["flight_id"] is None
    assert result["flight"] is None
    assert result["stdout"][0]["text"] == "hi"


def test_run_error_script_reports_line(client):
    source = (
        "from djitellopy import Tello\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "t.move_forward(600)\n"
    )
    response = client.post("/api/run", json={"source": source, "script_name": "blad.py"})
    flight = _wait(client, response.json()["id"])["flight"]
    assert flight["status"] == "error"
    assert flight["errors"][0]["line"] == 5


def test_upload_file(client):
    files = {"file": ("wgrany.py", SQUARE.encode("utf-8"), "text/x-python")}
    response = client.post("/api/upload", files=files, data={"adapter": "tello"})
    assert response.status_code == 200
    result = _wait(client, response.json()["id"])
    assert result["status"] == "done"
    assert result["flight"]["script_name"] == "wgrany.py"


def test_upload_rejects_non_python(client):
    files = {"file": ("notatka.txt", b"hello", "text/plain")}
    assert client.post("/api/upload", files=files).status_code == 400


def test_run_unknown_adapter(client):
    response = client.post("/api/run", json={"source": SQUARE, "adapter": "nieistniejacy"})
    assert response.status_code == 400


def test_run_empty_source(client):
    assert client.post("/api/run", json={"source": "   "}).status_code == 400


def test_csv_export(client):
    response = client.post("/api/run", json={"source": SQUARE, "script_name": "csv.py"})
    flight = _wait(client, response.json()["id"])["flight"]
    csv_response = client.get(f"/api/flights/{flight['id']}/csv")
    assert csv_response.status_code == 200
    text = csv_response.text.lstrip("\ufeff")
    header = text.splitlines()[0]
    assert header.startswith("t,x,y,z,yaw,vx,vy,vz,battery,state")
    assert len(text.splitlines()) > 10


def test_json_download_and_import(client):
    response = client.post("/api/run", json={"source": SQUARE, "script_name": "import.py"})
    flight = _wait(client, response.json()["id"])["flight"]
    download = client.get(f"/api/flights/{flight['id']}/json")
    assert download.status_code == 200
    imported = client.post("/api/flights/import",
                           files={"file": ("lot.json", download.content, "application/json")})
    assert imported.status_code == 200
    new_id = imported.json()["id"]
    assert new_id != flight["id"]
    assert client.get(f"/api/flights/{new_id}").json()["samples"]
    client.delete(f"/api/flights/{new_id}")


def test_import_invalid_json(client):
    response = client.post("/api/flights/import",
                           files={"file": ("x.json", b"{nie json", "application/json")})
    assert response.status_code == 400


def test_delete_flight(client):
    response = client.post("/api/run", json={"source": "print(1)", "script_name": "del.py"})
    flight = _wait(client, response.json()["id"])["flight"]
    assert client.delete(f"/api/flights/{flight['id']}").status_code == 200
    assert client.get(f"/api/flights/{flight['id']}").status_code == 404
    assert client.delete(f"/api/flights/{flight['id']}").status_code == 404


def test_unknown_flight_404(client):
    assert client.get("/api/flights/nie-ma-takiego").status_code == 404


def test_flight_id_traversal_rejected(client):
    assert client.get("/api/flights/..%2F..%2Fetc").status_code in (404, 400)


def test_stop_run_saves_partial_flight(client):
    """Stop: proces zabity, lot zapisany ze statusem 'stopped' i telemetrią do przerwania."""
    source = (
        "from djitellopy import Tello\n"
        "import time\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "t.move_forward(100)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    started = client.post("/api/run", json={"source": source, "script_name": "stop.py",
                                            "timeout": 60})
    assert started.status_code == 200
    run_id = started.json()["id"]
    # poczekaj, aż skrypt wykona takeoff i kawałek ruchu
    deadline = time.time() + 10
    while time.time() < deadline:
        live = client.get(f"/api/run/live/{run_id}").json()
        events = (live.get("live") or {}).get("events") or []
        if len(events) >= 3:
            break
        time.sleep(0.05)

    stop = client.post(f"/api/run/stop/{run_id}")
    assert stop.status_code == 200
    assert stop.json()["stopped"] is True

    result = _wait(client, run_id, timeout=15)
    assert result["status"] == "done"
    flight = result["flight"]
    assert flight["status"] == "stopped"
    assert any(e["type"] == "StoppedError" for e in flight["errors"])
    assert len(flight["samples"]) > 0
    assert len(flight["events"]) >= 3
    assert flight["duration"] > 0
    # historia zawiera lot z opisem przerwania
    stored = client.get(f"/api/flights/{flight['id']}").json()
    assert stored["status"] == "stopped"
    client.delete(f"/api/flights/{flight['id']}")


def test_stop_unknown_run_404(client):
    assert client.post("/api/run/stop/nie-ma-takiego").status_code == 404


def test_shutdown_kills_running_scripts():
    """Zamknięcie serwera zabija procesy skryptów (brak osieroconych pythonów)."""
    with TestClient(app) as client:
        started = client.post("/api/run", json={
            "source": "while True:\n    pass\n", "script_name": "loop.py",
            "timeout": 120, "save": False})
        run_id = started.json()["id"]
        deadline = time.time() + 10
        while time.time() < deadline and run_id not in runner.active_processes():
            time.sleep(0.05)
        pids = runner.running_script_pids()
        assert pids, "proces skryptu nie wystartował"
    # po wyjściu z bloku TestClient wysyła zdarzenie shutdown
    time.sleep(1.0)
    assert not runner.running_script_pids()
    if os.name == "nt":
        for pid in pids:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True).stdout
            assert str(pid) not in out
