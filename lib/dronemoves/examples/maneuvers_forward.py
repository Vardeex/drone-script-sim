"""Przykład: prosty ruch do przodu z rozpędzaniem i hamowaniem."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        pilot.forward(100)   # płynny ruch 1 m
        pilot.hover(1)       # chwila zawisu
        pilot.forward(50)    # jeszcze pół metra
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
