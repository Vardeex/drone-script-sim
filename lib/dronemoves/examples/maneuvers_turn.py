"""Przykład: płynny zakręt łukiem (nos podąża za torem)."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        pilot.forward(80)
        pilot.turn(90, radius=80)    # skręt w PRAWO (dodatni kąt = w prawo, jak w Tello)
        pilot.forward(80)
        pilot.turn(-90, radius=80)   # skręt w LEWO (ujemny kąt)
        pilot.forward(80)
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
