"""Przykład 2: wznoszenie, obroty i ruch `go_xyz_speed` (przód/lewo/góra).

Pokazuje ruch w układzie drona po obrocie oraz komendy z prędkością.
"""

import sys

from djitellopy import Tello

# polskie znaki w print() wymagają UTF-8 (konsola Windows domyślnie go nie ma)
for _strumien in (sys.stdout, sys.stderr):
    try:
        _strumien.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

tello = Tello()
tello.connect()
tello.takeoff()

# wznoszenie na 1,5 m (takeoff daje ok. 80 cm)
tello.move_up(70)
print("Wysokość:", tello.get_height(), "cm")

# obrót w lewo o 90 stopni, potem trójkąt ruchem xyz
tello.rotate_counter_clockwise(90)
tello.go_xyz_speed(100, 0, 0, 40)
tello.rotate_counter_clockwise(120)
tello.go_xyz_speed(100, 0, 0, 40)
tello.rotate_counter_clockwise(120)
tello.go_xyz_speed(100, 0, 0, 40)

# pełny obrót i opadanie
tello.rotate_clockwise(360)
tello.move_down(50)
print("Yaw:", tello.get_yaw(), "stopnie")

tello.land()
tello.end()
