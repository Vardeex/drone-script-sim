"""Slalom z bramkami - wersja poprawna (wszystkie bramki zaliczone).

Uruchom w symulatorze z wybraną sceną ``gate_slalom`` (UI -> Przeszkody albo
``./start.bat`` i wybór sceny w panelu). Dron leci po osi X i przelatuje przez
trzy bramki: środek, po lewej (y = +45 cm), po prawej (y = -45 cm).

W układzie projektu: x = przód, y = lewo, z = góra, start w (0, 0, 0).
"""

from djitellopy import Tello

SPEED = 40


def main() -> None:
    tello = Tello()
    tello.connect()
    tello.takeoff()                      # wznosi się na 80 cm
    tello.set_speed(SPEED)
    try:
        tello.move_forward(150)          # przelot przez bramkę 1 (x = 150, y = 0)
        tello.move_forward(20)           # wylot 20 cm za ramę (x = 170)
        tello.move_left(45)              # na y = +45
        tello.move_forward(110)          # x = 280, tuż przed bramką 2
        tello.move_forward(40)           # przelot przez bramkę 2 (x = 300) -> x = 320
        tello.move_right(90)             # na y = -45
        tello.move_forward(110)          # x = 430, tuż przed bramką 3
        tello.move_forward(40)           # przelot przez bramkę 3 (x = 450) -> x = 470
    finally:
        tello.land()


if __name__ == "__main__":
    main()
