"""Przykład: wznoszenie po spirali (stały promień, rosnąca wysokość)."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40, height_cm=30, max_height_cm=250)
    try:
        pilot.spiral(radius=100, height=100, turns=2)
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
