"""Przykład: ósemka - dwa okręgi styczne w punkcie startu."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=35)
    try:
        pilot.figure_eight(radius=80)
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
