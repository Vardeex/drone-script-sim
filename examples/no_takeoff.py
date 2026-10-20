"""Przykład 5: ruch bez startu.

Tello odrzuca komendy ruchu, gdy nie jest w powietrzu. Symulator zgłasza
błąd (jak djitellopy) z numerem linii skryptu.
"""

from djitellopy import Tello

tello = Tello()
tello.connect()

# brak takeoff() - kolejna komenda zakończy się błędem
tello.move_forward(100)

tello.end()
