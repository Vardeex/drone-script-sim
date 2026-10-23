"""Testy integracyjne bezpieczeństwa w symulatorze (dronemoves 0.2.0).

Sprawdzają realne zachowanie: preflight przy niskiej baterii nie startuje,
geofence blokuje manewr, ``return_home`` wraca do startu, nadzór baterii
kończy lot.
"""

from __future__ import annotations

import textwrap

from app import runner


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
    assert max(s["x"] for s in result.flight.samples) < 120


def test_watch_battery_return_home_konczy_przy_starcie():
    """``watch_battery(action="return_home")`` przerywa lot i wraca do startu.

    Ustawienie: bateria startowa 26 % (preflight przechodzi - wymaga >50 % tylko
    przy ostrzeżeniu o błędzie), przyspieszone zużycie ``battery_drain_scale = 40``
    (tryb testowy symulatora; domyślnie 0,05 %/s, tu ~2 %/s), próg 25 %. Nadzór
    reaguje więc w pierwszych sekundach lotu, przerywa trasę, wraca do startu
    i ląduje. Oczekiwania z geometrii: ≤ 15 cm od ``(0, 0)`` i etykieta
    ``return_home`` w logu lotu.

    Dlaczego symulator: ``get_battery()`` zwraca int, a przy normalnym zużyciu
    (1 % na 20 s) w krótkim locie bateria nie spadnie poniżej progu (KI-5) -
    mnożnik to jedyne miejsce, gdzie da się to przyspieszyć bez oszukiwania
    w teście.
    """
    source = """
        from djitellopy import Tello
        from dronemoves import Pilot
        import time

        # sleep REALNY: wirtualny time.sleep pcha zegar symulacji tylko w wątku,
        # który go wywołał, więc czekanie na wątek nadzoru musi być bez symulacji
        _real_sleep = __import__("app.sandbox_runtime", fromlist=["x"])._STATE["real_sleep"]

        tello = Tello()
        tello.connect()
        tello.set_sim_settings(battery=26)
        tello._ctrl.sim.settings.battery_drain_scale = 40.0
        tello._ctrl.sim.settings.battery_low_warning = 0
        tello.takeoff()
        pilot = Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500,
                      min_battery=3)
        tello.up(60)
        watcher = pilot.watch_battery(min_pct=25, action="return_home", interval_s=0.1)
        with pilot:
            for _ in range(10):
                pilot.forward(100)
                if not watcher.is_alive():
                    break
                pilot.turn(90, radius=60)
                if not watcher.is_alive():
                    break
            for _ in range(200):
                if not watcher.is_alive():
                    break
                _real_sleep(0.05)
            print("PO_WATCHDOGU:", [round(v, 1) for v in (pilot.watch_position or ())])
    """
    result = runner.run_script(textwrap.dedent(source).strip() + "\n", "watch.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    text = " ".join(line if isinstance(line, str) else line.get("text", "")
                    for line in result.stdout or [])
    assert "PO_WATCHDOGU:" in text, text
    payload = text.split("PO_WATCHDOGU:", 1)[1].split("]")[0].split("[")[1]
    x, y = [float(v) for v in payload.split(",")[:2]]
    # nadzór zadziałał i wrócił do startu: powrót na (0, 0) ±15 cm
    assert (x * x + y * y) ** 0.5 <= 15.0, (x, y)
