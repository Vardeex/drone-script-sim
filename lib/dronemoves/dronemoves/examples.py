"""Pomocniki do przykładów biblioteki (start i lądowanie lotu demonstracyjnego).

W symulatorze ``djitellopy`` jest mockiem, więc skrypt nie łączy się z dronem.
Na prawdziwym Tello ta sama funkcja połączy się i wystartuje.

Przykład::

    from dronemoves import examples

    tello, pilot = examples.start(speed=40)
    try:
        pilot.forward(100)
    finally:
        examples.finish(tello)
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

__all__ = ["start", "finish", "MIN_BATTERY"]

#: minimalna bateria do lotu demonstracyjnego (%)
MIN_BATTERY = 25


def start(speed: float = 40.0, height_cm: int = 50,
          min_battery: int = MIN_BATTERY, **pilot_kwargs: Any) -> Tuple[Any, Any]:
    """Połącz, wystartuj i wznij się - zwraca ``(tello, pilot)``.

    Pilot nie jest w bloku ``with`` - przykłady lądują jawnie w ``finally``,
    żeby pokazać pełną sekwencję start/lot/lądowanie.
    ``pilot_kwargs`` trafiają do ``Pilot`` (np. ``max_height_cm``).
    """
    from djitellopy import Tello  # leniwe - import dronemoves nie wymaga djitellopy

    from .pilot import Pilot

    tello = Tello()
    tello.connect()
    battery: Optional[int] = tello.get_battery()
    if battery is not None and battery < min_battery:
        raise SystemExit(
            f"Bateria {battery}% jest za niska do lotu demonstracyjnego "
            f"(min. {min_battery}%)."
        )
    tello.takeoff()
    if height_cm:
        tello.move_up(height_cm)
    pilot = Pilot(tello, speed=speed, **pilot_kwargs)
    return tello, pilot


def finish(tello: Any) -> None:
    """Wyląduj (bezpieczne zakończenie przykładu)."""
    tello.land()
