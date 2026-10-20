"""Limity i stałe modelu DJI Tello (niezmienne w czasie lotu).

Wartości wzięte z dokumentacji/API Tello i źródła djitellopy. Ruch liniowy
20-500 cm, obrót 1-360 deg, prędkość 10-100 cm/s, wysokość 10-500 cm,
prędkość RC -100..100.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Tuple


@dataclass(frozen=True)
class TelloLimits:
    """Zbiór limitów zakresów komend Tello."""

    name: str = "DJI Tello"
    #: ruch liniowy (cm)
    move_min_cm: int = 20
    move_max_cm: int = 500
    #: obrót (deg)
    rotate_min_deg: int = 1
    rotate_max_deg: int = 360
    #: prędkość (cm/s)
    speed_min: int = 10
    speed_max: int = 100
    default_speed: int = 50
    #: wysokość (cm)
    min_height_cm: int = 10
    max_height_cm: int = 500
    #: czas między komendami (s)
    min_command_time_s: float = 0.3
    #: limit czasu komendy (s) - Tello odrzuca po ~15 s, my tylko ostrzegamy
    command_timeout_s: float = 15.0
    #: bateria: pojemność i zużycie
    battery_full: int = 100
    #: pobór mocy w locie (% na sekundę) - przyjęte założenie symulacji
    battery_drain_flight_pct_per_s: float = 0.05
    battery_drain_idle_pct_per_s: float = 0.002
    #: wysokość startu po takeoff (cm)
    takeoff_height_cm: int = 80
    land_height_cm: int = 5
    #: prędkość przy wznoszeniu/opadaniu (cm/s) - założenie symulacji
    vertical_speed_cm_s: int = 50
    #: obsługiwane kierunki flip
    flip_directions: Tuple[str, ...] = ("l", "r", "f", "b")
    #: domyślne parametry RC
    rc_range: int = 100

    def as_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["flip_directions"] = list(self.flip_directions)
        return data


LIMITS = TelloLimits()

#: znormalizowane opisy do wyświetlenia w UI
RANGES = {
    "move_cm": (LIMITS.move_min_cm, LIMITS.move_max_cm),
    "rotate_deg": (LIMITS.rotate_min_deg, LIMITS.rotate_max_deg),
    "speed_cms": (LIMITS.speed_min, LIMITS.speed_max),
    "height_cm": (LIMITS.min_height_cm, LIMITS.max_height_cm),
    "rc": (-LIMITS.rc_range, LIMITS.rc_range),
}
