"""Slalom z bramkami - wersja z kolizją (dron uderza w ramę bramki 2).

Ten sam lot co ``obstacles_demo.py``, ale dron nie zjeżdża wystarczająco w lewo
przed bramką 2 - dolatuje do jej ramy. Symulacja lotu przebiega bez zmian
(przeszkody nie odbijają drona) - funkcja „Przeszkody 3D” pokazuje kolizję na
trasie i wpis na liście problemów.

Uruchom ze sceną ``gate_slalom``.
"""

from djitellopy import Tello


def main() -> None:
    tello = Tello()
    tello.connect()
    tello.takeoff()
    tello.set_speed(40)
    try:
        tello.move_forward(150)          # przelot przez bramkę 1 (zaliczona)
        tello.move_forward(20)           # wylot za ramę
        tello.move_forward(130)          # x = 300 - w płaszczyźnie bramki 2, ale na y = 0
        tello.move_forward(40)           # lot w poprzek ramy bramki 2 (otwór jest na
        #                                  y = +45 ± 45) -> dron uderza w ramę
    finally:
        tello.land()


if __name__ == "__main__":
    main()
