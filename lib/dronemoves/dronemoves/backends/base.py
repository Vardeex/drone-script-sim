"""Interfejs backendu ruchu - mostek między trajektorią a dronem.

Manewry i executor nie wiedzą, jak steruje się konkretnym dronem; znają tylko
ten interfejs. Nowy dron = nowy backend (np. ``pymavlink``), manewry bez zmian.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BackendError(RuntimeError):
    """Błąd komunikacji z dronem (np. brak odpowiedzi na komendę RC)."""


class MotionBackend(ABC):
    """Abstrakcyjny backend ruchu.

    Wszystkie prędkości liniowe w cm/s, prędkości obrotu w °/s (plus = w lewo),
    zgodnie z układem drona: X do przodu, Y w lewo, Z w górę.
    """

    #: nazwa backendu (diagnostyka)
    name: str = "base"

    @abstractmethod
    def rc(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        """Ustaw wychylenia drążków RC: ``-100..100``.

        :param vx: przód (+) / tył (-)
        :param vy: lewo (+) / prawo (-)
        :param vz: góra (+) / dół (-)
        :param yaw_rate: obrót w lewo (+)
        """

    @abstractmethod
    def stop(self) -> None:
        """Natychmiastowe zatrzymanie ruchu: ``rc(0, 0, 0, 0)``."""

    # ------------------------------------------------ opcjonalne (native)
    def go(self, x: int, y: int, z: int, speed: int) -> None:
        """Ruch do punktu (względnego, w układzie drona) z prędkością ``speed``.

        Backendy obsługujące tryb ``native`` nadpisują tę metodę.
        """
        raise NotImplementedError(f"Backend {self.name!r} nie obsługuje go_xyz_speed")

    def curve(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, speed: int) -> None:
        """Ruch po łuku (punkt kontrolny + punkt docelowy, układ drona)."""
        raise NotImplementedError(f"Backend {self.name!r} nie obsługuje curve_xyz_speed")

    def supports_native(self) -> bool:
        """Czy backend potrafi wykonywać manewry trybem ``native``?"""
        return False

    # ------------------------------------------------------ integracja/UI
    def annotate(self, label: str) -> None:
        """Oznacz początek/koniec manewru (tylko mock symulatora).

        Domyślnie nic nie robi - prawdziwe drony nie mają takiej metody.
        """

    def get_battery(self) -> Optional[int]:
        """Poziom baterii (%) albo ``None``, jeśli niedostępny."""
        return None

    def get_height(self) -> Optional[int]:
        """Wysokość nad ziemią [cm] albo ``None``."""
        return None


class BackendAdapter(MotionBackend):
    """Backend delegujący do obiektu drona (np. ``djitellopy.Tello``)."""

    def __init__(self, drone: object) -> None:
        self.drone = drone

    def _call(self, method: str, *args: object) -> bool:
        """Wywołaj metodę drona, jeśli istnieje; zwróć True, gdy się udało."""
        func = getattr(self.drone, method, None)
        if func is None:
            return False
        func(*args)
        return True
