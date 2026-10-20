"""Przykład: płynny zakręt łukiem (nos podąża za torem)."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        pilot.forward(80)
        pilot.turn(90, radius=80)    # skręt w lewo łukiem o promieniu 80 cm
        pilot.forward(80)
        pilot.turn(-90, radius=80)   # skręt w prawo (ujemny kąt)
        pilot.forward(80)
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
