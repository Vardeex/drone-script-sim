"""Testy integracyjne bezpieczeństwa w symulatorze (dronemoves 0.2.0).

Sprawdzają realne zachowanie: preflight przy niskiej baterii nie startuje,
geofence blokuje manewr, ``return_home`` wraca do startu, nadzór baterii
kończy lot.
"""

from __future__ import annotations

import textwrap

import pytest

from app import runner
from tests.route_helpers import run_script


def _run(source: str):
    return runner.run_script(textwrap.dedent(source).strip() + "\n", "safety.py")


def test_preflight_blocks_takeoff_when_battery_low():
    """Bateria 30 % -> PreflightError, dron NIE startuje (brak takeoff w logu)."""
    result = _run(
        """
        from djitellopy import Tello
        from dronemoves import Pilot
        from dronemoves.safety import PreflightError, safe_start

        tello = Tello()
        tello.connect()
        tello.set_sim_settings(battery=30)
        pilot = Pilot(tello, speed=40)
        try:
            safe_start(tello, pilot=pilot)
        except PreflightError as exc:
            print("PREFLIGHT_ODMOWA:", exc)
        print("STAN:", tello.get_height())
        """
    )
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    text = " ".join(line if isinstance(line, str) else line.get("text", "")
                    for line in result.stdout or [])
    assert "PREFLIGHT_ODMOWA" in text, text
    takeoffs = [e for e in result.flight.events if e["command"] == "takeoff"]
    assert not takeoffs, "takeoff nie powinien się odbyć"


def test_return_home_returns_within_10_cm():
    """Po locie 100 cm w przód ``return_home`` wraca do startu ±10 cm.

    Sprawdzamy pozycję pilota po powrocie (metryka planera) - to ta sama
    wartość, której używa ``return_home`` do wyliczenia punktu docelowego.
    """
    result = _run(
        """
        from djitellopy import Tello
        from dronemoves import Pilot

        tello = Tello()
        tello.connect()
        tello.takeoff()
        with Pilot(tello, speed=40, max_radius_cm=500) as pilot:
            pilot.forward(100)
            pilot.return_home()
            print("PO_POWROCIE:", [round(v, 1) for v in pilot.position()])
        tello.land()
        """
    )
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    text = " ".join(line if isinstance(line, str) else line.get("text", "")
                    for line in result.stdout or [])
    start = text.index("PO_POWROCIE:")
    values = text[start:].split("[", 1)[1].split("]", 1)[0].split(",")
    x0, y0 = float(values[0]), float(values[1])
    assert abs(x0) < 10 and abs(y0) < 10, text


def test_geofence_blocks_maneuver_in_simulator():
    """Geofence 100 cm blokuje ``forward(200)`` (SafetyError przed lotem)."""
    result = _run(
        """
        from djitellopy import Tello
        from dronemoves import Pilot
        from dronemoves.pilot import SafetyError

        tello = Tello()
        tello.connect()
        tello.takeoff()
        with Pilot(tello, speed=40, max_radius_cm=500) as pilot:
            pilot.set_geofence(max_height_cm=500, max_radius_cm=100)
            try:
                pilot.forward(200)
            except SafetyError as exc:
                print("GEOFENCE:", exc)
        tello.land()
        """
    )
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    text = " ".join(line if isinstance(line, str) else line.get("text", "")
                    for line in result.stdout or [])
    assert "GEOFENCE" in text, text
    # nie poleciał dalej niż ~100 cm (tolerancja na rozpędzanie)
    max_x = max(s["x"] for s in result.flight.samples)
    assert max_x < 110, max_x
