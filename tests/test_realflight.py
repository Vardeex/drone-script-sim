"""Testy importu i porównania lotu rzeczywistego (``app/realflight.py``).

Oczekiwania liczone z geometrii: dwa tory różniące się o znane przesunięcie
(np. 10 cm w ``x``) muszą dać dokładnie taką odchyłkę, a rozkład błędu na
składowe (wzdłuż/w bok/w pionie) musi wskazywać właściwą oś.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import realflight, storage
from app.server import app


def make_flight(source: str, samples: List[Dict[str, Any]],
                name: str = "lot.py", flight_id: str = "test") -> Dict[str, Any]:
    """Minimalny lot w formacie symulatora (tylko to, czego używa porównanie)."""
    return {
        "format": "drone-script-simulator", "version": 1,
        "source": source, "id": flight_id, "created_at": "2026-10-25T10:00:00+00:00",
        "script_name": name, "adapter": "tello", "status": "ok",
        "final_state": "landed", "duration": samples[-1]["t"] if samples else 0.0,
        "real_seconds": 0.0, "stats": {}, "limits": {}, "script_source": "",
        "samples": samples, "events": [], "segments": [], "warnings": [],
        "errors": [], "stdout": [], "stderr": [],
    }


def straight(x_cm: float = 0.0, y_cm: float = 0.0, z_cm: float = 80.0,
             speed_cm_s: float = 25.0, duration: float = 4.0,
             step: float = 0.1) -> List[Dict[str, Any]]:
    """Tor w linii prostej po ``x`` z prędkością ``speed_cm_s``."""
    samples = []
    moment = 0.0
    while moment <= duration + 1e-9:
        samples.append({"t": round(moment, 2), "x": round(x_cm + speed_cm_s * moment, 2),
                        "y": round(y_cm, 2), "z": round(z_cm, 2), "yaw": 0.0,
                        "vx": speed_cm_s, "vy": 0.0, "vz": 0.0, "battery": 90.0,
                        "state": "airborne"})
        moment += step
    return samples


# ------------------------------------------------------------------- walidacja
def test_validate_real_accepts_recorder_file():
    """Plik rejestratora (``source: real``) przechodzi walidację."""
    payload = make_flight("real", straight())
    assert realflight.validate_real(payload) is payload


@pytest.mark.parametrize("mutation,message", [
    (lambda p: p.pop("source"), "rzeczywisty"),
    (lambda p: p.update(source="sim"), "rzeczywisty"),
    (lambda p: p.update(samples=[]), "za mało próbek"),
    (lambda p: p["samples"][0].pop("x"), "nie ma pola 'x'"),
])
def test_validate_real_rejects_bad_files(mutation, message):
    """Zły plik daje czytelny komunikat (a nie wyjątek w środku porównania)."""
    payload = make_flight("real", straight())
    mutation(payload)
    with pytest.raises(ValueError) as info:
        realflight.validate_real(payload)
    assert message in str(info.value)


# ------------------------------------------------------------------ porównanie
def test_compare_identical_flights_is_zero():
    """Ten sam tor dwa razy -> zerowa odchyłka."""
    payload = make_flight("real", straight())
    result = realflight.compare(payload, payload)
    assert result["report"]["max_error_cm"] == pytest.approx(0.0, abs=1e-6)
    assert result["report"]["mean_error_cm"] == pytest.approx(0.0, abs=1e-6)
    assert result["report"]["points"] > 30


def test_compare_detects_known_offset():
    """Przesunięcie 10 cm w ``x`` -> maksymalna odchyłka 10 cm."""
    real = make_flight("real", straight())
    sim = make_flight("sim", straight(x_cm=10.0))
    report = realflight.compare(real, sim)["report"]
    assert report["max_error_cm"] == pytest.approx(10.0, abs=0.2)
    assert report["mean_error_cm"] == pytest.approx(10.0, abs=0.2)
    # przesunięcie jest wzdłuż toru (dron leci po x), nie w bok
    assert report["mean_along_cm"] == pytest.approx(10.0, abs=0.3)
    assert abs(report["mean_cross_cm"]) < 0.2


def test_compare_detects_vertical_offset():
    """Różnica wysokości 15 cm -> składowa pionowa 15 cm i podpowiedź o pionie."""
    real = make_flight("real", straight(z_cm=80.0))
    sim = make_flight("sim", straight(z_cm=95.0))
    report = realflight.compare(real, sim)["report"]
    assert report["mean_vertical_cm"] == pytest.approx(15.0, abs=0.2)
    assert any("wysokości" in hint for hint in report["hints"]), report["hints"]


def test_compare_detects_speed_scale():
    """Symulacja 2× szybsza -> droga 2× dłuższa i podpowiedź o ``max_speed_cm_s``."""
    real = make_flight("real", straight(speed_cm_s=20.0))
    sim = make_flight("sim", straight(speed_cm_s=40.0))
    report = realflight.compare(real, sim)["report"]
    assert report["sim_path_cm"] == pytest.approx(2 * report["real_path_cm"], rel=0.05)
    assert any("max_speed_cm_s" in hint for hint in report["hints"]), report["hints"]


def test_compare_requires_overlapping_time():
    """Loty bez wspólnego okna czasowego -> czytelny błąd."""
    real = make_flight("real", straight())
    shifted = straight()
    for sample in shifted:
        sample["t"] = sample["t"] + 100.0
    sim = make_flight("sim", shifted)
    with pytest.raises(ValueError):
        realflight.compare(real, sim)


def test_series_is_downsampled():
    """Seria do wykresu jest ograniczona, ale zachowuje pierwszy i ostatni punkt."""
    real = make_flight("real", straight(duration=200.0, step=0.1))
    result = realflight.compare(real, real, step_s=0.1)
    assert len(result["series"]) <= realflight.PLOT_POINTS
    assert result["series"][0]["t"] == pytest.approx(0.0, abs=0.1)
    assert result["series"][-1]["t"] == pytest.approx(200.0, abs=0.5)


# ------------------------------------------------------------------------ API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Klient API z historią lotów w katalogu tymczasowym (nie zaśmieca repo)."""
    from app import paths

    monkeypatch.setattr(paths, "FLIGHTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "UPLOADS_DIR", tmp_path / "_uploads")
    monkeypatch.setattr(paths, "ensure_dirs", lambda: None)
    with TestClient(app) as test_client:
        yield test_client


def _upload(client, payload: Dict[str, Any]):
    data = json.dumps(payload).encode("utf-8")
    return client.post("/api/flights/import-real",
                       files={"file": ("lot_real.json", data, "application/json")})


def test_api_import_and_compare(client):
    """Import lotu rzeczywistego, potem porównanie z lotem symulowanym."""
    real = make_flight("real", straight(), name="real.py")
    imported = _upload(client, real)
    assert imported.status_code == 200, imported.text
    real_id = imported.json()["id"]
    assert imported.json()["source"] == "real"
    assert imported.json()["samples"] == len(real["samples"])

    sim = make_flight("sim", straight(x_cm=8.0), name="sym.py")
    sim_id = storage.save_imported(sim)["id"]

    listed = client.get("/api/flights").json()
    by_id = {item["id"]: item for item in listed}
    assert by_id[real_id]["source"] == "real"
    assert by_id[sim_id]["source"] == "sim"

    compared = client.post("/api/flights/compare",
                           json={"real_id": real_id, "sim_id": sim_id})
    assert compared.status_code == 200, compared.text
    report = compared.json()["report"]
    assert report["max_error_cm"] == pytest.approx(8.0, abs=0.3)
    assert report["hints"]
    assert compared.json()["series"]


def test_api_rejects_non_real_file(client):
    """Lot symulatora podany jako „rzeczywisty” -> 400 z wyjaśnieniem."""
    response = _upload(client, make_flight("sim", straight()))
    assert response.status_code == 400
    assert "rzeczywisty" in response.json()["detail"]


def test_api_compare_requires_real_first(client):
    """Odwrotna kolejność (symulowany jako pierwszy) -> 400."""
    real_id = _upload(client, make_flight("real", straight())).json()["id"]
    sim_id = storage.save_imported(make_flight("sim", straight()))["id"]
    swapped = client.post("/api/flights/compare",
                          json={"real_id": sim_id, "sim_id": real_id})
    assert swapped.status_code == 400
    missing = client.post("/api/flights/compare",
                          json={"real_id": real_id, "sim_id": "nie-ma-takiego"})
    assert missing.status_code == 404
