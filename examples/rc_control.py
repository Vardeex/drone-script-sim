"""Przykład 3: lot trybem RC (send_rc_control) + time.sleep.

W symulacji ruch RC jest całkowany w czasie trwania time.sleep:
prędkość [cm/s] = (wychylenie / 100) * set_speed.
"""

import time

from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.set_speed(50)

# przód 2 s -> 100 cm, obrót w lewo 1 s -> 90 deg
tello.send_rc_control(0, 50, 0, 0)
time.sleep(2)
tello.send_rc_control(0, 50, 0, 100)
time.sleep(1)

# lewo 1,5 s i w górę 1 s
tello.send_rc_control(50, 0, 0, 0)
time.sleep(1.5)
tello.send_rc_control(0, 0, 80, 0)
time.sleep(1)

# zatrzymanie
tello.send_rc_control(0, 0, 0, 0)
time.sleep(0.5)
print("Pozycja po manewrach - wysokość:", tello.get_height(), "cm")

tello.land()
tello.end()
