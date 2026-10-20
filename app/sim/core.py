"""Silnik symulacji lotu - niezależny od marki drona.

Silnik przechowuje stan drona, prowadzi wirtualny zegar, planuje i wykonuje
segmenty ruchu (przy pomocy :mod:`app.sim.physics`) oraz zapisuje telemetrię
i zdarzenia. Adapter konkretnej biblioteki (np. djitellopy) tłumaczy wywołania
API na metody :class:`Simulation`.

Zasada działania: skrypt wykonuje się synchronicznie, ale każda komenda
"przewija" wirtualny zegar o czas, jaki zajęłaby na prawdziwym dronie.
Dzięki temu skrypt kończy się natychmiast (rzeczywisty czas), a symulacja
ma realną oś czasu do odtwarzania w UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import physics

#: Interwał próbkowania telemetrii (s czasu symulacji).
TELEMETRY_DT = 0.05

#: Stany drona.
STATE_IDLE = "idle"
STATE_AIRBORNE = "airborne"
STATE_LANDED = "landed"
STATE_EMERGENCY = "emergency"
STATE_ERROR = "error"

Vec3 = physics.Vec3


class SimulationError(Exception):
    """Błąd symulacji (np. komenda niedozwolona w danym stanie)."""


@dataclass
class Settings:
    """Parametry silnika."""

    #: jeśli True, ruchy mają rampę przyspieszenia/hamowania
    accel: bool = False
    accel_value: float = physics.DEFAULT_ACCEL
    #: mnożnik prędkości pionowej (takeoff/land/up/down)
    vertical_speed: float = 50.0
    takeoff_height: float = 80.0
    land_height: float = 0.0
    battery_drain_flight: float = 0.05
    battery_drain_idle: float = 0.002
    default_speed: int = 50
    #: maksymalny czas symulacji (s) - zabezpieczenie przed nieskończonymi pętlami
    max_sim_time: float = 3600.0


@dataclass
class Event:
    """Zdarzenie = jedno wywołanie API (komenda) przez skrypt."""

    index: int
    t: float
    t_end: float
    command: str
    args: List[Any]
    status: str  # ok | warning | error
    warning: Optional[str] = None
    message: Optional[str] = None
    line: Optional[int] = None
    file: Optional[str] = None
    position: Vec3 = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    battery: float = 100.0
    duration: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "t": round(self.t, 4),
            "t_end": round(self.t_end, 4),
            "duration": round(self.duration, 4),
            "command": self.command,
            "args": self.args,
            "status": self.status,
            "warning": self.warning,
            "message": self.message,
            "line": self.line,
            "file": self.file,
            "x": round(self.position[0], 2),
            "y": round(self.position[1], 2),
            "z": round(self.position[2], 2),
            "yaw": round(self.yaw, 2),
            "battery": round(self.battery, 2),
        }


@dataclass
class Sample:
    """Pojedyncza próbka telemetrii."""

    t: float
    x: float
    y: float
    z: float
    yaw: float
    vx: float
    vy: float
    vz: float
    battery: float
    state: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t": round(self.t, 3),
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "z": round(self.z, 2),
            "yaw": round(self.yaw, 2),
            "vx": round(self.vx, 2),
            "vy": round(self.vy, 2),
            "vz": round(self.vz, 2),
            "battery": round(self.battery, 2),
            "state": self.state,
        }


@dataclass
class Segment:
    """Odcinek ruchu na osi czasu (używany do interpolacji w UI)."""

    t0: float
    t1: float
    move: physics.LinearMove
    yaw0: float = 0.0
    yaw1: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "t0": round(self.t0, 4),
            "t1": round(self.t1, 4),
            "yaw0": round(self.yaw0, 2),
            "yaw1": round(self.yaw1, 2),
            "points": [[round(c, 2) for c in p] for p in self.move.polyline],
        }


class FlightRecorder:
    """Zbieracz telemetrii, zdarzeń i ostrzeżeń z jednego lotu."""

    def __init__(self) -> None:
        self.samples: List[Sample] = []
        self.events: List[Event] = []
        self.warnings: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.segments: List[Segment] = []

    def record(self, sample: Sample) -> None:
        self.samples.append(sample)

    def add_warning(self, message: str, line: Optional[int] = None, file: Optional[str] = None,
                    t: Optional[float] = None, command: Optional[str] = None) -> None:
        self.warnings.append({
            "message": message, "line": line, "file": file,
            "t": round(t, 3) if t is not None else None, "command": command,
        })

    def add_error(self, message: str, line: Optional[int] = None, file: Optional[str] = None,
                  type_: str = "error", traceback: Optional[str] = None) -> None:
        self.errors.append({
            "message": message, "line": line, "file": file,
            "type": type_, "traceback": traceback,
        })


@dataclass
class FlightData:
    """Wynik symulacji jednego skryptu (serializowany do JSON)."""

    script_name: str = ""
    adapter: str = ""
    started_at: str = ""
    duration: float = 0.0
    samples: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    stdout: List[Dict[str, Any]] = field(default_factory=list)
    stderr: List[Dict[str, Any]] = field(default_factory=list)
    script_source: str = ""
    limits: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok | error | timeout
    final_state: str = STATE_IDLE


class Simulation:
    """Stan drona i wirtualny zegar.

    Czas: ``now`` to czas symulacji w sekundach. Każda komenda ruchu planuje
    segment od ``now`` do ``now + czas``, a następnie zegar "przeskakuje".
    Próbki telemetrii są generowane w interwale :data:`TELEMETRY_DT`.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.recorder = FlightRecorder()

        # stan fizyczny
        self.position: Vec3 = (0.0, 0.0, 0.0)
        self.yaw: float = 0.0
        self.velocity: Vec3 = (0.0, 0.0, 0.0)
        self.speed: int = int(self.settings.default_speed)
        self.battery: float = 100.0
        self.state: str = STATE_IDLE

        # zegar
        self.now: float = 0.0
        self._next_sample_t: float = 0.0

        # liczniki / historia
        self.distance: float = 0.0
        self.max_height: float = 0.0
        self.flight_time: float = 0.0
        self.takeoff_t: Optional[float] = None
        self.battery_start: float = 100.0

        # tryb RC: ostatnie komendy RC
        self._rc: Tuple[int, int, int, int] = (0.0, 0.0, 0.0, 0.0)  # type: ignore[assignment]

        #: aktywne segmenty (plan) - używane do próbkowania i interpolacji
        self._segments: List[Segment] = []
        #: stos znaczników czasowych dla wydarzeń (indeks zdarzenia)
        self._event_stack: List[Event] = []

        self.sample(force=True)

    # ------------------------------------------------------------ telemetria
    def sample(self, force: bool = False) -> None:
        rec = self.recorder
        if not force and self.now + 1e-9 < self._next_sample_t:
            return
        rec.record(Sample(
            t=self.now, x=self.position[0], y=self.position[1], z=self.position[2],
            yaw=self.yaw % 360.0, vx=self.velocity[0], vy=self.velocity[1], vz=self.velocity[2],
            battery=self.battery, state=self.state,
        ))
        # następna próbka na siatce 50 ms
        self._next_sample_t = (math.floor(self.now / TELEMETRY_DT + 1e-9) + 1) * TELEMETRY_DT

    def _drain_samples(self, t_from: float, t_to: float) -> None:
        """Wygeneruj próbki w przedziale przy użyciu aktywnego segmentu."""
        if t_to <= t_from:
            return
        t = self._next_sample_t
        while t < t_to - 1e-9:
            if t >= t_from - 1e-9:
                pos, vel, yaw = self._state_at(t)
                self.recorder.record(Sample(
                    t=t, x=pos[0], y=pos[1], z=pos[2], yaw=yaw % 360.0,
                    vx=vel[0], vy=vel[1], vz=vel[2], battery=self._battery_at(t), state=self.state,
                ))
            t = round(t + TELEMETRY_DT, 6)
        self._next_sample_t = t

    def _state_at(self, t: float) -> Tuple[Vec3, Vec3, float]:
        """Pozycja, prędkość i yaw w chwili ``t`` (z aktywnego segmentu)."""
        for seg in reversed(self.recorder.segments):
            if seg.t0 - 1e-9 <= t <= seg.t1 + 1e-9:
                elapsed = min(max(t - seg.t0, 0.0), seg.t1 - seg.t0)
                pos = seg.move.position_at(elapsed)
                vel = seg.move.velocity_at(elapsed)
                span = seg.t1 - seg.t0
                frac = 0.0 if span <= 0 else elapsed / span
                return pos, vel, seg.yaw0 + (seg.yaw1 - seg.yaw0) * frac
        return self.position, self.velocity, self.yaw

    def _battery_at(self, t: float) -> float:
        """Bateria w chwili t - interpolacja liniowa między próbkami start/end."""
        if not self.recorder.samples:
            return self.battery
        return self._last_battery_at_start

    # --------------------------------------------------------------- zegar
    def advance(self, seconds: float, drain_idle: bool = True) -> None:
        """Przesuń wirtualny zegar o ``seconds`` (bez ruchu, np. time.sleep)."""
        if seconds < 0:
            raise SimulationError("Czas nie może być ujemny.")
        self._check_sim_time(self.now + seconds)
        t0, t1 = self.now, self.now + seconds
        self._segments = []
        self._drain_samples(t0, t1)
        if drain_idle:
            rate = self.settings.battery_drain_flight if self.state == STATE_AIRBORNE \
                else self.settings.battery_drain_idle
            self.battery = max(0.0, self.battery - rate * seconds)
        if self.state == STATE_AIRBORNE:
            self.flight_time += seconds
        self.now = t1
        self.velocity = (0.0, 0.0, 0.0)
        self.sample(force=True)
