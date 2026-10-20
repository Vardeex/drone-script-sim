"""Executor: odtwarzanie trajektorii przez ``send_rc_control`` z korektą czasu.

Wysyła wychylenia RC z częstotliwością 20 Hz według planu, ale mierzy
**rzeczywisty** czas (``time.monotonic``) - jeśli pętla się spóźni, przeskakuje
w trajektorii do właściwej chwili zamiast zwalniać. Dzięki temu manewr trwa
tyle, ile zaplanowano, nawet gdy wywołania drona są wolniejsze.

Executor nie zna drona: dostaje backend (``MotionBackend``).
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from .backends.base import MotionBackend
from .trajectory import Trajectory

__all__ = ["Executor", "ExecuteResult"]

#: Częstotliwość wysyłania RC (Hz) - Tello wymaga komendy co <= 100 ms.
CONTROL_HZ = 20.0


class ExecuteResult:
    """Wynik wykonania trajektorii."""

    def __init__(self, duration: float, samples_sent: int, real_seconds: float,
                 stopped: bool = False) -> None:
        self.duration = duration
        self.samples_sent = samples_sent
        self.real_seconds = real_seconds
        self.stopped = stopped

    def __repr__(self) -> str:  # pragma: no cover - diagnostyka
        return (f"ExecuteResult(duration={self.duration:.2f}, sent={self.samples_sent}, "
                f"real={self.real_seconds:.2f}, stopped={self.stopped})")


class Executor:
    """Wysyła RC według trajektorii, z korektą czasu rzeczywistego."""

    def __init__(self, backend: MotionBackend, frequency_hz: float = CONTROL_HZ,
                 time_fn: Callable[[], float] = time.monotonic,
                 sleep_fn: Callable[[float], None] = time.sleep) -> None:
        if frequency_hz <= 0:
            raise ValueError("frequency_hz musi być dodatnie")
        self.backend = backend
        self.period = 1.0 / frequency_hz
        self._time = time_fn
        self._sleep = sleep_fn
        self._stop = threading.Event()

    def stop(self) -> None:
        """Przerwij pętlę (np. z innego wątku przy Ctrl+C)."""
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def execute(self, trajectory: Trajectory) -> ExecuteResult:
        """Odtwórz trajektorię. Na końcu zawsze wysyła ``stop()``."""
        if not trajectory.samples:
            raise ValueError("Pusta trajektoria")
        self._stop.clear()
        duration = trajectory.duration
        started = self._time()
        sent = 0
        stopped = False
        try:
            while True:
                elapsed = self._time() - started
                if elapsed >= duration:
                    break
                # korekta czasu: próbka dla faktycznie minionej chwili
                sample = trajectory.at(elapsed)
                fb, lr, ud, yaw = sample.rc
                # djitellopy: send_rc_control(left_right, forward_backward, up_down, yaw)
                self.backend.rc(vx=fb, vy=lr, vz=ud, yaw_rate=yaw)
                sent += 1
                if self._stop.is_set():
                    stopped = True
                    break
                # sen do następnego taktu, liczony od startu (bez dryfu)
                next_tick = (sent * self.period)
                remaining = next_tick - (self._time() - started)
                if remaining > 0:
                    self._sleep(remaining)
        finally:
            self.backend.rc(vx=0, vy=0, vz=0, yaw_rate=0)
            self.backend.stop()
        return ExecuteResult(duration=duration, samples_sent=sent,
                             real_seconds=self._time() - started, stopped=stopped)
