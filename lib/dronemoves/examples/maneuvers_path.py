"""Przykład: przelot przez punkty względne (gładki spline)."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40, max_height_cm=250)
    try:
        # punkty (x, y, z) względem miejsca startu manewru, w cm
        pilot.path([(100, 0, 0), (200, 100, 50), (300, 0, 0)], smooth=True)
        pilot.path([(0, -100, -50), (0, 0, 0)], smooth=False)  # prosta łamana
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
