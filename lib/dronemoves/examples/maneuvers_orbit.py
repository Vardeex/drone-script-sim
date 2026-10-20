"""Przykład: krążenie wokół punktu z nosem zawsze skierowanym do środka."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        pilot.orbit(radius=120, turns=1)                     # jedno okrążenie
        pilot.orbit(radius=100, turns=2, direction="left")   # dwa okrążenia w lewo
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
