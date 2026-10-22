"""Przykład: preflight i bezpieczny start (dronemoves 0.2.0).

Pokazuje ``Pilot.preflight()`` (raport bez startu) i ``safe_start()``
(preflight + takeoff). Skrypt działa w symulatorze i na prawdziwym Tello.
"""

from djitellopy import Tello
from dronemoves import Pilot, PreflightError, preflight, safe_start


def main() -> None:
    tello = Tello()
    tello.connect()

    # 1. Raport przedstartowy - nic nie startuje
    report = preflight(tello, plan_eta_s=120)
    print("=== Preflight ===")
    print(report)
    if not report.ok:
        print("Błędy krytyczne:", [c.message for c in report.errors])

    # 2. Bezpieczny start: preflight -> takeoff -> sprawdzenie wysokości
    pilot = Pilot(tello, speed=40, max_height_cm=300, max_radius_cm=300)
    try:
        safe_start(tello, pilot=pilot, confirm=True, countdown_s=2)
    except PreflightError as exc:
        print("Start wstrzymany:", exc)
        return

    try:
        with pilot:
            pilot.forward(100)
            pilot.safe_land()
    finally:
        print("Koniec:", pilot.ground_height(), "cm")


main()
