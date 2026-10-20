"""Przykład 1: start, kwadrat o boku 100 cm, lądowanie.

Po każdym boku dron obraca się o 90 stopni w prawo, więc wraca
do punktu startu z yaw = 0.
"""

from djitellopy import Tello

tello = Tello()
tello.connect()
print(f"Bateria przed startem: {tello.get_battery()}%")

tello.takeoff()

for side in range(4):
    tello.move_forward(100)
    tello.rotate_clockwise(90)
    print(f"Bok {side + 1}/4 wykonany, wysokość: {tello.get_height()} cm")

tello.land()
print(f"Czas lotu: {tello.get_flight_time()} s, bateria: {tello.get_battery()}%")
tello.end()
