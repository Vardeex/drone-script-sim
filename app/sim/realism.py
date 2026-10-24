"""Tryb realistyczny symulatora - założenia o niedoskonałościach prawdziwego Tello.

Tryb jest **domyślnie wyłączony**: przy ``realism = False`` silnik liczy ruch
dokładnie jak dotąd (bit w bit - patrz ``test_realism_ideal_unchanged``).

==============================  ===========================================
parametr                        założenie (NIE pomiar z drona)
==============================  ===========================================
dryf poziomy                    losowy spacer z prędkością 2-6 cm/s; co
                                ``drift_interval_s`` (1 s) nowy kierunek, więc
                                dryf jest wolniejszy niż kompensacja w locie
szum wysokości                  ±2 cm (``height_noise_cm``), 1 σ
szum kursu                      ±1,5° (``yaw_noise_deg``), 1 σ
opóźnienie RC                   100 ms - komendy RC działają ze zwłoką
niedokładność ``move_*``        ±5 % odległości (``move_error``)
seed                            powtarzalność (ten sam seed = ten sam lot)
==============================  ===========================================

Parametry są **założeniami**, nie zmierzonymi wartościami: prawdziwy Tello
dryfuje różnie w zależności od wiatru, podłoża i kalibracji IMU. Tryb służy
temu, żeby zobaczyć, jak skrypt zachowa się, gdy dron nie jest idealny
(np. czy ``return_home`` nadal trafi w miejsce startu).

Losowość: :class:`random.Random` z ``seed`` - każda symulacja dostaje własny
generator, więc dwa uruchomienia z tym samym seedem dają identyczny lot.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Tuple

Vec2 = Tuple[float, float]


@dataclass
class RealismParams:
    """Parametry trybu realistycznego (wszystkie wartości to założenia)."""

    #: włączony tryb realistyczny
    enabled: bool = False
    #: ziarno losowości (powtarzalność)
    seed: int = 1
    #: minimalna / maksymalna prędkość dryfu poziomego [cm/s]
    drift_speed_min: float = 2.0
    drift_speed_max: float = 6.0
    #: co ile sekund losowany jest nowy kierunek dryfu [s]
    drift_interval_s: float = 1.0
    #: odchylenie standardowe szumu wysokości [cm]
    height_noise_cm: float = 2.0
    #: odchylenie standardowe szumu kursu [°]
    yaw_noise_deg: float = 1.5
    #: opóźnienie reakcji na komendy RC [s]
    rc_delay_s: float = 0.1
    #: względna niedokładność ``move_*`` (0.05 = ±5 %)
    move_error: float = 0.05


class Drift:
    """Poziomy dryf drona: losowy spacer (nowy kierunek co ``interval`` sekund)."""

    def __init__(self, params: RealismParams, rng: Optional[random.Random] = None) -> None:
        self.params = params
        self.rng = rng or random.Random(params.seed)
        self._velocity: Vec2 = (0.0, 0.0)
        self._next_change = 0.0

    def velocity_at(self, t: float) -> Vec2:
        """Prędkość dryfu ``(vx, vy)`` w chwili ``t`` (cm/s, układ świata).

        Kierunek zmienia się co ``drift_interval_s``; prędkość jest stała w
        przedziale, więc całkowanie po kroku jest dokładne.
        """
        if t >= self._next_change:
            angle = self.rng.uniform(0.0, 2.0 * math.pi)
            speed = self.rng.uniform(self.params.drift_speed_min,
                                     self.params.drift_speed_max)
            self._velocity = (speed * math.cos(angle), speed * math.sin(angle))
            steps = math.floor((t - self._next_change) / self.params.drift_interval_s) + 1
            self._next_change += steps * self.params.drift_interval_s
        return self._velocity

    def displacement(self, t0: float, t1: float) -> Vec2:
        """Przemieszczenie od ``t0`` do ``t1`` (całka prędkości dryfu)."""
        if t1 <= t0:
            return (0.0, 0.0)
        dx = dy = 0.0
        t = t0
        while t < t1 - 1e-12:
            vx, vy = self.velocity_at(t)
            end = min(t1, self._next_change)
            dt = max(end - t, 0.0)
            dx += vx * dt
            dy += vy * dt
            t = end if end > t else t1
        return (dx, dy)


def move_scale(params: RealismParams, rng: random.Random) -> float:
    """Mnożnik odległości ``move_*``: 1 ± ``move_error`` (rozkład jednostajny)."""
    if not params.enabled or params.move_error <= 0:
        return 1.0
    return 1.0 + rng.uniform(-params.move_error, params.move_error)


def noisy(value: float, sigma: float, rng: random.Random) -> float:
    """Odczyt z szumem Gaussa (``sigma`` = 0 -> wartość bez zmian)."""
    if sigma <= 0:
        return value
    return value + rng.gauss(0.0, sigma)
