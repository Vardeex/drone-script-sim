"""Kalibracja profilu RC na prawdziwym Tello (pomiar taśmą).

Skrypt leci przez ``--seconds`` sekund z pełnym wychyleniem drążka, po czym
pyta o zmierzony dystans i zapisuje profil JSON.

Użycie (tylko na otwartej przestrzeni, bez przeszkód w torze lotu!):

    python calibrate.py --seconds 2.0 --out profil.json

Wczytanie profilu: ``Pilot(tello, profile_path="profil.json")``.
"""

import argparse
import sys
import time

from djitellopy import Tello

from dronemoves import CalibrationProfile, save_profile

RC = 100  # pełne wychylenie drążka


def main() -> int:
    parser = argparse.ArgumentParser(description="Kalibracja dronemoves (Tello)")
    parser.add_argument("--seconds", type=float, default=2.0,
                        help="czas lotu z rc=100 (sekundy)")
    parser.add_argument("--out", default="profil.json", help="plik wyjściowy (JSON)")
    args = parser.parse_args()

    tello = Tello()
    tello.connect()
    battery = tello.get_battery() or 0
    print(f"bateria: {battery}%")
    if battery < 40:
        print("Za niska bateria do kalibracji (min. 40%).")
        return 2

    print(f"Lecę {args.seconds:.1f} s z rc={RC}. Trzymaj drona w zasięgu!")
    tello.takeoff()
    tello.move_up(50)
    try:
        tello.send_rc_control(0, RC, 0, 0)  # fb=100: do przodu
        time.sleep(args.seconds)
    finally:
        tello.send_rc_control(0, 0, 0, 0)
        tello.land()

    try:
        zmierzono = float(input("Zmierz taśmą dystans [cm] i podaj: ").replace(",", "."))
    except (EOFError, ValueError):
        print("Brak pomiaru - profil nie zapisany.")
        return 1

    profile = CalibrationProfile().with_measurements("forward", zmierzono, args.seconds)
    save_profile(profile, args.out)
    print(f"Zapisano {args.out}: {profile.max_speed_cm_s:.1f} cm/s przy rc={RC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
