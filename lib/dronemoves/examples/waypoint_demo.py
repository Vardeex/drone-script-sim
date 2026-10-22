"""Przykład: trasa z punktów z nadzorem baterii i powrotem do startu.

``watch_battery`` działa w tle: gdy bateria spadnie poniżej progu, pilot
przerywa lot, wraca do startu i ląduje.
"""

import time

from djitellopy import Tello
from dronemoves import Pilot, safe_start


def main() -> None:
    tello = Tello()
    tello.connect()
    pilot = Pilot(tello, speed=40, max_height_cm=300, max_radius_cm=400,
                  min_battery=15)
    safe_start(tello, pilot=pilot)

    # nadzór baterii: przy < 25 % wróć do startu i wyląduj
    pilot.watch_battery(min_pct=25, action="return_home", interval_s=1.0)

    try:
        with pilot:
            # punkty względne wobec pozycji po starcie (0, 0, 0 = tu jestem)
            pilot.path([(150, 0, 20), (150, 120, 20), (0, 120, 0)], smooth=True)
            pilot.hover(1.0)
            pilot.return_home()
            print("Po powrocie:", [round(v, 1) for v in pilot.position()])
    finally:
        time.sleep(0.1)
        pilot.safe_land()


main()
