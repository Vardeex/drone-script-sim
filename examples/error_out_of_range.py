"""Przykład 4: komenda poza zakresem Tello.

`move_forward(600)` przekracza limit 500 cm - symulator zgłosi błąd
(w taki sam sposób, w jaki odrzuciłby komendę prawdziwy dron) i przerwie
skrypt. W panelu „Problemy” zobaczysz linię z błędem.
"""

from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()

tello.move_forward(300)   # poprawna komenda
tello.move_forward(600)   # BŁĄD: 600 cm > 500 cm

tello.land()              # nie zostanie wykonane
tello.end()
