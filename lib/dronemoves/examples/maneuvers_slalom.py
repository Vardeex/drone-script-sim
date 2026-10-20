"""Przykład: slalom między bramkami (środki bramek co ``spacing`` cm)."""

from dronemoves import examples


def main() -> None:
    tello, pilot = examples.start(speed=40)
    try:
        # 4 bramki co 100 cm, szerokość toru 60 cm
        pilot.slalom(gates=4, spacing=100, width=60)
    finally:
        examples.finish(tello)


if __name__ == "__main__":
    main()
