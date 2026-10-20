"""Przykład: łuk (część okręgu) i pełne okrążenie."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        pilot.arc(180, radius=100)                         # półkole
        pilot.circle(radius=100, direction="left")         # pełne okrążenie w lewo
        pilot.circle(radius=80, direction="right", face="center")  # nos do środka
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
