"""Wspólne narzędzia testów biblioteki (bez symulatora i bez djitellopy)."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import pytest

from dronemoves.backends.base import MotionBackend


class FakeClock:
    """Zegar wirtualny: ``sleep`` przesuwa czas zamiast czekać (testy błyskawiczne)."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.now += seconds


class FakeDrone:
    """Minimalny zamiennik ``djitellopy.Tello`` dla backendu Tello.

    Rejestruje wszystkie wywołania RC; opcjonalnie potrafi rzucić wyjątkiem
    (do testu zachowania przy awarii). Symuluje wysokość i baterię.
    """

    def __init__(self, battery: int = 100, height: int = 80,
                 fail_after: Optional[int] = None) -> None:
        self.battery = battery
        self.height = height
        self.fail_after = fail_after
        self.rc_calls: List[Tuple[int, int, int, int]] = []
        self.annotations: List[str] = []
        self.landed = 0

    def send_rc_control(self, lr: int, fb: int, ud: int, yaw: int) -> None:
        if self.fail_after is not None and len(self.rc_calls) >= self.fail_after:
            raise RuntimeError("utrata łączności (test)")
        self.rc_calls.append((lr, fb, ud, yaw))

    def annotate(self, label: str) -> None:
        self.annotations.append(label)

    def get_battery(self) -> int:
        return self.battery

    def get_height(self) -> int:
        return self.height

    def land(self) -> None:
        self.landed += 1


class RecordingBackend(MotionBackend):
    """Backend zapisujący wywołania (bez Tello) - do testów executor/manewrów."""

    name = "recording"

    def __init__(self) -> None:
        self.calls: List[Tuple[int, int, int, int]] = []
        self.stops = 0
        self.annotations: List[str] = []

    def rc(self, vx: float, vy: float, vz: float, yaw_rate: float) -> None:
        self.calls.append((int(vx), int(vy), int(vz), int(yaw_rate)))

    def stop(self) -> None:
        self.stops += 1

    def annotate(self, label: str) -> None:
        self.annotations.append(label)

    def get_height(self) -> int:
        return 80

    def get_battery(self) -> int:
        return 100


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_drone() -> FakeDrone:
    return FakeDrone()


def distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
