"""Przykład pokazowy: kilka manewrów w jednej płynnej sekwencji.

Sekwencja jest planowana w całości i odtwarzana bez zatrzymań, a przed lotem
widać cały tor (``preview`` zapisuje go też do symulatora).
"""

import math

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40, max_height_cm=250)
    try:
        m = pilot.maneuvers()
        lot = [
            m.forward(80),
            m.turn(90, radius=80),
            m.circle(radius=100, direction="right"),
            m.orbit(radius=120, turns=1, direction="left"),
            m.path([(100, 0, 0), (200, 80, 40), (280, 0, 0)]),
            m.figure_eight(radius=70),
        ]
        # podgląd: zaplanowany tor bez lotu (lista punktów w cm)
        tor = pilot.preview(m.forward(80))
        print(f"pierwszy manewr: {len(tor)} punktów, koniec {tor[-1]}")

        pilot.sequence(lot)

        x, y, z = pilot.position()
        print(f"koniec lotu: x={x:.0f} y={y:.0f} z={z:.0f} cm, yaw={pilot.yaw:.0f}°")
        print(f"odległość od startu: {math.hypot(x, y):.0f} cm")
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
