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

import inspect
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import physics

#: Interwał próbkowania telemetrii (s czasu symulacji).
TELEMETRY_DT = 0.05

#: Maksymalny krok całkowania ruchu RC (s). Tello przyjmuje ``rc`` co 100 ms,
#: biblioteka wysyła co 50 ms - symulator całkuje z tym samym krokiem.
RC_STEP = 0.05

#: Stany drona.
STATE_IDLE = "idle"
STATE_AIRBORNE = "airborne"
STATE_LANDED = "landed"
STATE_EMERGENCY = "emergency"
STATE_ERROR = "error"

Vec3 = physics.Vec3


class SimulationError(Exception):
    """Błąd symulacji (np. komenda niedozwolona w danym stanie)."""


class CommandError(SimulationError):
    """Błąd wywołania komendy (z opcjonalną lokalizacją w skrypcie)."""

    def __init__(self, message: str, line: Optional[int] = None, file: Optional[str] = None,
                 kind: str = "command") -> None:
        super().__init__(message)
        self.line = line
        self.file = file
        self.kind = kind


@dataclass(frozen=True)
class RcProfile:
    """Przelicznik wychyleń RC na prędkości - odpowiednik profilu kalibracji.

    Wzory są **identyczne** jak w ``dronemoves.calibration.CalibrationProfile``
    (``rc / 100 * max``, opcjonalna martwa strefa i wykładnik nieliniowości),
    dzięki czemu symulator wykonuje dokładnie to, co zaplanowała biblioteka.

    :param max_speed_cm_s: prędkość przy ``rc = 100`` (cm/s)
    :param max_yaw_rate_dps: obrót przy ``rc = 100`` (°/s)
    :param max_vertical_cm_s: prędkość pionowa przy ``ud = 100`` (cm/s)
    :param deadzone: wychylenie poniżej tej wartości = 0
    :param response_exponent: wykładnik nieliniowości (1.0 = liniowo)
    """

    max_speed_cm_s: float = 50.0
    max_yaw_rate_dps: float = 90.0
    max_vertical_cm_s: float = 50.0
    deadzone: int = 0
    response_exponent: float = 1.0

    def _shape(self, rc: float) -> float:
        value = max(-100.0, min(100.0, float(rc))) / 100.0
        if abs(value) * 100.0 <= self.deadzone:
            return 0.0
        sign = -1.0 if value < 0 else 1.0
        return sign * (abs(value) ** self.response_exponent)

    def rc_to_speed(self, rc: float) -> float:
        """Wychylenie ``rc`` -> prędkość liniowa [cm/s]."""
        return self._shape(rc) * self.max_speed_cm_s

    def rc_to_yaw_rate(self, rc: float) -> float:
        """Wychylenie ``rc`` (obrót) -> prędkość kątowa [°/s], plus = w prawo."""
        return self._shape(rc) * self.max_yaw_rate_dps

    def rc_to_vertical(self, rc: float) -> float:
        """Wychylenie ``rc`` (pion) -> prędkość pionowa [cm/s], plus = w górę."""
        return self._shape(rc) * self.max_vertical_cm_s


#: Profil domyślny: DJI Tello (100% drążka = 50 cm/s poziomo, 90 °/s obrotu).
def default_rc_profile() -> RcProfile:
    return RcProfile()


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
    #: profil zamiany wychyleń RC na prędkości (cm/s, °/s) - ten sam, którego
    #: używa biblioteka dronemoves (domyślnie profil Tello)
    rc_profile: "RcProfile" = field(default_factory=default_rc_profile)
    #: maksymalny czas symulacji (s) - zabezpieczenie przed nieskończonymi pętlami
    max_sim_time: float = 3600.0
    #: maksymalna wysokość (cm) - limit drona wynika z adaptera
    max_height_cm: float = 500.0


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
class SampleSpan:
    """Przedział czasu między dwiema komendami skryptu.

    Przechowuje stan na początku (``position``/``yaw``/``velocity``) oraz
    opcjonalny ruch (``motion``). Próbki telemetrii w przedziale są
    interpolowane, a bateria maleje liniowo od ``battery0`` do ``battery1``.
    """

    t0: float
    t1: float
    motion: Optional["MotionSpan"] = None
    state: str = STATE_IDLE
    position: Vec3 = (0.0, 0.0, 0.0)
    velocity: Vec3 = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    battery0: float = 100.0
    battery1: float = 100.0
    battery_rate: float = 0.0  # %/s

    def _elapsed(self, t: float) -> float:
        return min(max(t - self.t0, 0.0), max(self.t1 - self.t0, 0.0))

    def state_at(self, t: float) -> Tuple[Vec3, Vec3, float]:
        """Pozycja, prędkość i yaw w chwili ``t``."""
        if self.motion is None:
            return self.position, (0.0, 0.0, 0.0), self.yaw
        elapsed = self._elapsed(t)
        pos = self.motion.move.position_at(elapsed)
        vel = self.motion.move.velocity_at(elapsed)
        span = self.t1 - self.t0
        frac = 0.0 if span <= 0 else elapsed / span
        yaw0, yaw1 = self.motion.yaw0, self.motion.yaw1
        return pos, vel, yaw0 + (yaw1 - yaw0) * frac


@dataclass
class MotionSpan:
    """Ruch wykonywany w przedziale czasu: łamana + obrót yaw."""

    move: physics.LinearMove
    yaw0: float = 0.0
    yaw1: float = 0.0

    def as_dict(self, t0: float, t1: float) -> Dict[str, Any]:
        return {
            "t0": round(t0, 4),
            "t1": round(t1, 4),
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
        self.spans: List["SampleSpan"] = []

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
    real_seconds: float = 0.0
    #: zaplanowana trajektoria manewrów (biblioteka dronemoves): [{x, y, z, t, label}]
    planned_trail: List[Dict[str, Any]] = field(default_factory=list)


class Simulation:
    """Stan drona i wirtualny zegar.

    Czas: ``now`` to czas symulacji w sekundach. Każda komenda planuje
    przedział (``SampleSpan``) od ``now`` do ``now + czas``, a następnie zegar
    "przeskakuje". Telemetria jest próbkowana na siatce :data:`TELEMETRY_DT`
    (50 ms), a wartości w próbkach są interpolowane w obrębie przedziału
    (pozycja, prędkość, yaw i bateria).

    Stany: ``idle`` (na ziemi, przed startem), ``airborne`` (w locie),
    ``landed`` (wylądował), ``emergency`` (awaryjne zatrzymanie silników),
    ``error`` (błąd krytyczny, np. rozładowana bateria).
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.recorder = FlightRecorder()

        # stan fizyczny (pozycja w cm, yaw w stopniach, prędkość w cm/s)
        self.position: Vec3 = (0.0, 0.0, 0.0)
        self.yaw: float = 0.0
        self.velocity: Vec3 = (0.0, 0.0, 0.0)
        self.speed: int = int(self.settings.default_speed)
        self.battery: float = 100.0
        self.state: str = STATE_IDLE

        # zegar
        self.now: float = 0.0
        self._next_sample_t: float = TELEMETRY_DT

        # liczniki / statystyki
        self.distance: float = 0.0
        self.max_height: float = 0.0
        self.flight_time: float = 0.0
        self.takeoff_t: Optional[float] = None
        self.land_t: Optional[float] = None
        self.battery_start: float = 100.0

        # tryb RC - ostatnia komenda (tylko do raportowania)
        self._rc: Tuple[int, int, int, int] = (0, 0, 0, 0)

        #: ostatnia informacja o bieżącej komendzie (do śledzenia numeru linii)
        self.current_command: Optional[Event] = None
        #: licznik zdarzeń
        self._event_seq = 0
        #: flaga: przekroczono maksymalny czas symulacji
        self.time_exceeded = False

        self._record_sample(0.0, self.position, (0.0, 0.0, 0.0), 0.0, self.state, self.battery)

    # ------------------------------------------------------------------ stan
    @property
    def airborne(self) -> bool:
        return self.state == STATE_AIRBORNE

    def _record_sample(self, t: float, pos: Vec3, vel: Vec3, yaw: float, state: str,
                       battery: float) -> None:
        self.recorder.record(Sample(
            t=t, x=pos[0], y=pos[1], z=pos[2], yaw=(yaw % 360.0),
            vx=vel[0], vy=vel[1], vz=vel[2], battery=battery, state=state,
        ))

    def _check_sim_time(self, t: float) -> None:
        if t > self.settings.max_sim_time:
            self.time_exceeded = True
            raise SimulationError(
                f"Przekroczono maksymalny czas symulacji ({self.settings.max_sim_time:.0f} s). "
                "Skrypt prawdopodobnie zawiera zbyt długą pętlę."
            )

    # ---------------------------------------------------------------- zegar
    def advance(self, seconds: float) -> None:
        """Przesuń wirtualny zegar o ``seconds`` bez ruchu (np. ``time.sleep``)."""
        if seconds < 0:
            raise SimulationError("Czas nie może być ujemny.")
        self.advance_to(self.now + seconds)

    def advance_to(self, t: float) -> None:
        """Przesuń zegar do ``t`` (koniec przedziału), bez ruchu."""
        if t < self.now:
            raise SimulationError("Nie można cofnąć wirtualnego zegara.")
        span = self._run_span(self.now, t, motion=None)
        self.battery = self._drain_battery(span)
        self.velocity = (0.0, 0.0, 0.0)

    def _run_span(self, t0: float, t1: float,
                  motion: Optional["MotionSpan"]) -> "SampleSpan":
        """Zapisz przedział [t0, t1] i wygeneruj próbki na siatce 50 ms.

        Dla bardzo długich bezczynnych odcinków (np. ``sleep(600)`` w pętli)
        próbki są przerzedzane, aby nie generować setek tysięcy wpisów.
        """
        self._check_sim_time(t1)
        span = SampleSpan(
            t0=t0, t1=t1, motion=motion,
            state=self.state, position=self.position, velocity=self.velocity, yaw=self.yaw,
        )
        self.recorder.spans.append(span)

        duration = max(t1 - t0, 0.0)
        if motion is None and duration > 1.0:
            # długie oczekiwanie (np. sleep w pętli): nie potrzebujemy próbek co 50 ms
            step = min(1.0, max(TELEMETRY_DT, duration / 600.0))
            t = t0 + step
            while t < t1 - 1e-9:
                self._record_sample(t, self.position, (0.0, 0.0, 0.0), self.yaw,
                                    span.state, self.battery)
                t = round(t + step, 6)
            self._record_sample(t1, self.position, (0.0, 0.0, 0.0), self.yaw,
                                span.state, self.battery)
            self._next_sample_t = t1
            self.now = t1
            return span

        t = self._next_sample_t
        while t < t1 - 1e-9:
            pos, vel, yaw = span.state_at(t)
            self._record_sample(t, pos, vel, yaw, span.state, self.battery)
            t = round(t + TELEMETRY_DT, 6)
        self._next_sample_t = max(self._next_sample_t, t)
        self.now = t1
        return span

    def _drain_battery(self, span: "SampleSpan", extra_rate: float = 0.0) -> float:
        """Zmniejsz baterię o zużycie w przedziale i popraw baterię w próbkach."""
        duration = max(span.t1 - span.t0, 0.0)
        rate = self.settings.battery_drain_flight if span.state == STATE_AIRBORNE \
            else self.settings.battery_drain_idle
        rate += extra_rate
        new_level = max(0.0, self.battery - rate * duration)
        span.battery0 = self.battery
        span.battery1 = new_level
        span.battery_rate = rate
        self.battery = new_level
        if self.state == STATE_AIRBORNE:
            self.flight_time += duration
        # przelicz próbki z tego przedziału (zostały zapisane z baterią wyjściową)
        for sample in reversed(self.recorder.samples):
            if sample.t < span.t0 - 1e-9:
                break
            span_len = span.t1 - span.t0
            frac = 0.0 if span_len <= 0 else min(max((sample.t - span.t0) / span_len, 0.0), 1.0)
            sample.battery = span.battery0 + (span.battery1 - span.battery0) * frac
        return new_level

    def _add_distance(self, points: Sequence[Vec3]) -> None:
        """Sumuj długość przelotu (drogę poziomą) i aktualizuj maks. wysokość.

        Droga pionowa (takeoff/land/up/down) nie jest liczona do "dystansu" -
        w statystykach lotu dystans oznacza przelot nad ziemią.
        """
        for a, b in zip(points, points[1:]):
            self.distance += math.hypot(b[0] - a[0], b[1] - a[1])
        for p in points:
            if p[2] > self.max_height:
                self.max_height = p[2]

    def stats(self) -> Dict[str, Any]:
        return {
            "duration_s": round(self.now, 2),
            "flight_time_s": round(self.flight_time, 2),
            "distance_cm": round(self.distance, 1),
            "max_height_cm": round(self.max_height, 1),
            "battery_used_pct": round(self.battery_start - self.battery, 2),
            "battery_left_pct": round(self.battery, 2),
            "final_position_cm": [round(c, 1) for c in self.position],
            "final_yaw_deg": round(self.yaw % 360.0, 1),
            "samples": len(self.recorder.samples),
            "events": len(self.recorder.events),
            "warnings": len(self.recorder.warnings),
            "errors": len(self.recorder.errors),
        }

    # ------------------------------------------------------- lokalizacja kodu
    @staticmethod
    def caller_location() -> Tuple[Optional[str], Optional[int]]:
        """Znajdź plik i numer linii w skrypcie użytkownika (pierwsza ramka spoza app)."""
        from .. import paths

        app_root = str(paths.APP_DIR) + os.sep
        frame = inspect.currentframe()
        frame = frame.f_back if frame is not None else None  # pomiń caller_location
        try:
            while frame is not None:
                abs_name = os.path.abspath(frame.f_code.co_filename)
                if not abs_name.startswith(app_root) and "site-packages" not in abs_name \
                        and "lib" + os.sep not in abs_name.lower():
                    return os.path.basename(abs_name), frame.f_lineno
                frame = frame.f_back
        finally:
            del frame
        return None, None

    # -------------------------------------------------------------- zdarzenia
    def begin(self, command: str, args: Sequence[Any]) -> Tuple[Event, str, Optional[int]]:
        """Otwórz zdarzenie komendy (wywołaj przez adapter)."""
        file, line = self.caller_location()
        self._event_seq += 1
        event = Event(
            index=self._event_seq, t=self.now, t_end=self.now, command=command,
            args=list(args), status="ok", line=line, file=file,
            position=self.position, yaw=self.yaw % 360.0, battery=self.battery,
        )
        return event, (file or ""), line

    def commit(self, event: Event) -> Event:
        """Zapisz zdarzenie do rejestratora po wykonaniu."""
        event.t_end = self.now
        event.duration = round(self.now - event.t, 4)
        self.recorder.events.append(event)
        self.current_command = event
        self.after_command()
        return event

    #: hook ustawiany przez sandbox (zapis zrzutu stanu po komendzie)
    after_command_hook = None

    def after_command(self) -> None:
        hook = self.after_command_hook
        if hook is not None:
            try:
                hook(self)
            except Exception:
                pass

    def warn(self, message: str, event: Optional[Event] = None, command: Optional[str] = None) -> None:
        """Zapisz ostrzeżenie (i domyślnie oznacz zdarzenie jako ostrzeżenie)."""
        file, line = self.caller_location()
        if event is not None:
            file, line = event.file, event.line
            if event.status == "ok":
                event.status = "warning"
            if event.warning:
                event.warning += " | " + message
            else:
                event.warning = message
        self.recorder.add_warning(message, line=line, file=file, t=self.now, command=command)

    # -------------------------------------------------------- operacje ruchu
    def require_airborne(self, command: str) -> None:
        """Rzuć błąd, jeśli dron nie jest w locie (zachowanie jak w Tello)."""
        if not self.airborne:
            raise SimulationError(
                f"Komenda '{command}' wymaga, aby dron był w powietrzu (stan: {self.state}). "
                "Najpierw wywołaj takeoff()."
            )

    def check_ceiling(self, z: float, event: Optional[Event] = None) -> bool:
        """Ostrzeż, jeśli wysokość przekracza maksymalną wysokość drona.

        Ostrzeżenie trafia do zdarzenia komendy (z linią skryptu), więc skrypt
        nie zostaje przerwany, ale lot jest oznaczony jako ostrzeżenie.
        """
        limit = float(self.settings.max_height_cm)
        if z > limit:
            message = (f"Wysokość {z:.0f} cm przekracza maksymalną wysokość drona "
                       f"({limit:.0f} cm).")
            if event is not None:
                self.recorder.add_warning(message, line=event.line, file=event.file,
                                          t=self.now, command=event.command)
                if event.status == "ok":
                    event.status = "warning"
                event.warning = message if not event.warning else f"{event.warning} | {message}"
            else:
                self.recorder.add_warning(message, t=self.now)
            return False
        return True

    def _execute_motion(self, event: Event, move: physics.LinearMove,
                        yaw1: Optional[float] = None) -> None:
        """Wykonaj ruch: przesuń zegar o czas segmentu i zaktualizuj stan."""
        yaw0 = self.yaw
        yaw_end = yaw0 if yaw1 is None else yaw1
        # kąt nosa trzymamy w zakresie (-180, 180] jak get_yaw() Tello - dzięki temu
        # symulator i biblioteka (która normalizuje yaw % 360) mówią o tym samym kącie
        yaw_end = ((yaw_end + 180.0) % 360.0) - 180.0
        duration = move.duration()
        motion = MotionSpan(move=move, yaw0=yaw0, yaw1=yaw_end)
        span = self._run_span(self.now, self.now + duration, motion=motion)
        self._drain_battery(span)
        self.position = move.end
        self.yaw = yaw_end
        self.velocity = (0.0, 0.0, 0.0)
        self._add_distance(move.polyline)
        self.commit(event)

    def move_relative(self, command: str, args: Sequence[Any], dx: float, dy: float,
                      dz: float, speed: float, event: Event,
                      curve_control: Optional[Tuple[float, float, float]] = None,
                      accel: Optional[bool] = None) -> None:
        """Ruch względem aktualnej pozycji i yaw (dx przód, dy lewo, dz góra)."""
        points = physics.relative_move_points(
            self.position, self.yaw, dx, dy, dz, curve_control=curve_control)
        end = points[-1]
        use_accel = self.settings.accel if accel is None else accel
        move = physics.LinearMove(
            start=tuple(self.position), end=tuple(end), speed=float(speed),
            accel=use_accel, accel_value=self.settings.accel_value, polyline=points,
        )
        self.check_ceiling(end[2], event)
        self._execute_motion(event, move)

    def rotation(self, command: str, args: Sequence[Any], delta_deg: float,
                 event: Event) -> None:
        """Obrót w miejscu z prędkością obrotową (założenie: 90 deg/s).

        Dodajemy 100 ms "czasu reakcji", aby krótkie obroty były widoczne na osi czasu.
        """
        speed_deg_s = 90.0
        move = physics.LinearMove(start=tuple(self.position), end=tuple(self.position),
                                  speed=1.0, duration_override=max(abs(delta_deg) / speed_deg_s, 0.1))
        self._execute_motion(event, move, yaw1=self.yaw + delta_deg)

    def takeoff(self, event: Event, height: Optional[float] = None) -> None:
        """Start pionowy na zadaną/wysokość domyślną."""
        if self.state in (STATE_AIRBORNE, STATE_EMERGENCY):
            raise SimulationError("Dron już jest w powietrzu - takeoff nie jest możliwy.")
        target = self.settings.takeoff_height if height is None else height
        move = physics.LinearMove(
            start=tuple(self.position),
            end=(self.position[0], self.position[1], target),
            speed=float(self.settings.vertical_speed), accel=False,
        )
        self.state = STATE_AIRBORNE
        self.takeoff_t = self.now
        self._execute_motion(event, move)

    def land(self, event: Event) -> None:
        """Lądowanie na ziemi (z = 0)."""
        self.require_airborne("land")
        move = physics.LinearMove(
            start=tuple(self.position),
            end=(self.position[0], self.position[1], float(self.settings.land_height)),
            speed=float(self.settings.vertical_speed), accel=False,
        )
        self._execute_motion(event, move)
        self.state = STATE_LANDED
        self.land_t = self.now
        self._record_sample(self.now, self.position, self.velocity, self.yaw,
                            self.state, self.battery)

    def emergency(self, event: Event) -> None:
        """Awaryjne zatrzymanie silników - dron spada pionowo na ziemię."""
        if not self.airborne:
            self.warn("emergency wywołane, choć dron nie jest w powietrzu.", event=event)
        fall_speed = 300.0  # cm/s - swobodny spadek w przybliżeniu
        move = physics.LinearMove(
            start=tuple(self.position),
            end=(self.position[0], self.position[1], 0.0),
            speed=fall_speed, accel=False,
        )
        self._execute_motion(event, move)
        self.state = STATE_EMERGENCY
        self.land_t = self.now
        self._record_sample(self.now, self.position, self.velocity, self.yaw,
                            self.state, self.battery)

    # --------------------------------------------------------------------- RC
    def rc_motion(self, event: Event, lr: float, fb: float, ud: float, yaw_rate: float,
                  seconds: float) -> None:
        """Ruch z trybu RC trwający ``seconds`` sekund symulacji.

        Wejścia RC w konwencji djitellopy/Tello (``rc a b c d``), zweryfikowane
        w ``examples/manual-control-pygame.py``:

        * ``lr``  - wychylenie w prawo **dodatnie**, w lewo ujemne,
        * ``fb``  - przód dodatnie, tył ujemne,
        * ``ud``  - góra dodatnie, dół ujemne,
        * ``yaw_rate`` - obrót w prawo (zgodnie z zegarem) **dodatni**,
          w lewo ujemny - tak samo rośnie ``get_yaw()`` w Tello.

        Ruch jest całkowany w krokach <= 50 ms w układzie drona obracanym
        w trakcie (nos drona skręca razem z RC), więc łuk odpowiada temu,
        co robi biblioteka ``dronemoves`` (patrz :meth:`rc_profile_motion`).
        """
        self.require_airborne("send_rc_control")
        if seconds <= 0:
            self.commit(event)
            return
        prof = self.settings.rc_profile
        v_forward = prof.rc_to_speed(fb)          # cm/s
        v_right = prof.rc_to_speed(lr)            # cm/s (dodatnie = prawo)
        v_up = prof.rc_to_vertical(ud)            # cm/s
        # yaw: w symulatorze yaw rośnie w prawo (jak get_yaw()), więc +rc = +yaw.
        # ``integrate_rc`` oczekuje yaw_rate dodatniego = w prawo, więc przekazujemy
        # wartość z profilu bez zmiany znaku.
        yaw_rate = prof.rc_to_yaw_rate(yaw_rate)  # deg/s (dodatnie = w prawo)
        if not any((v_forward, v_right, v_up, yaw_rate)):
            self.advance(seconds)
            self.commit(event)
            return
        self.integrate_rc(event, v_forward, v_right, v_up, yaw_rate, seconds)

    def integrate_rc(self, event: Event, v_forward: float, v_right: float, v_up: float,
                     yaw_rate: float, seconds: float) -> None:
        """Całkuj ruch RC krokami <= :data:`RC_STEP`.

        ``v_forward``/``v_right`` to prędkości w **układzie drona** (przód / prawo),
        więc kierunek ruchu liczymy z bieżącego ``yaw`` (nos obraca się w trakcie
        ruchu - tak powstaje łuk). ``yaw_rate`` w °/s, dodatni = w prawo.

        Krok jest dzielony na połowę obrotu i przesunięcie z kątem środkowym
        (schemat punktu środkowego), dzięki czemu łuk jest gładki i niezależny
        od długości ``seconds`` (symulator i biblioteka dają ten sam wynik
        przy RC co 50 ms i przy większych porcjach czasu).
        """
        remaining = float(seconds)
        points: List[Vec3] = [tuple(self.position)]  # type: ignore[list-item]
        x, y, z = self.position
        yaw = self.yaw
        while remaining > 1e-9:
            dt = min(RC_STEP, remaining)
            remaining -= dt
            mid = yaw + yaw_rate * dt / 2.0        # kąt nosa w połowie kroku
            # kierunek nosa: (cos, sin); prawo = nos obrócony o -90 deg
            x += (v_forward * math.cos(math.radians(mid))
                  + v_right * math.cos(math.radians(mid - 90.0))) * dt
            y += (v_forward * math.sin(math.radians(mid))
                  + v_right * math.sin(math.radians(mid - 90.0))) * dt
            z += v_up * dt
            yaw += yaw_rate * dt
            points.append((x, y, z))
        speed = max(abs(v_forward), abs(v_right), abs(v_up), 0.01)
        move = physics.LinearMove(start=tuple(self.position), end=(x, y, z), speed=speed,
                                  polyline=points)
        self.check_ceiling(z, event)
        self._execute_motion(event, move, yaw1=yaw)

    def integrate_world(self, event: Event, vx: float, vy: float, v_up: float,
                        yaw_rate: float, seconds: float) -> None:
        """Całkuj ruch podany w układzie **globalnym** (vx, vy już obrócone).

        Używane, gdy trajektoria biblioteki podaje prędkości w układzie lotu
        (tak liczy ``dronemoves``: ``vx``/``vy`` próbki są w układzie globalnym,
        a ``yaw`` opisuje tylko orientację nosa).
        """
        remaining = float(seconds)
        points: List[Vec3] = [tuple(self.position)]  # type: ignore[list-item]
        x, y, z = self.position
        yaw = self.yaw
        while remaining > 1e-9:
            dt = min(RC_STEP, remaining)
            remaining -= dt
            x += vx * dt
            y += vy * dt
            z += v_up * dt
            yaw += yaw_rate * dt
            points.append((x, y, z))
        speed = max(math.hypot(vx, vy), abs(v_up), 0.01)
        move = physics.LinearMove(start=tuple(self.position), end=(x, y, z), speed=speed,
                                  polyline=points)
        self.check_ceiling(z, event)
        self._execute_motion(event, move, yaw1=yaw)

    def rc_profile_motion(self, event: Event, vx: float, vy: float, v_up: float,
                          yaw_rate: float, seconds: float, world: bool = False,
                          yaw: Optional[float] = None) -> None:
        """Ruch RC podany wprost w cm/s i deg/s (profil kalibracji biblioteki).

        Używane przez adapter, gdy skrypt steruje biblioteką ``dronemoves``:
        silnik nie przelicza wychyleń RC drugi raz, tylko wykonuje dokładnie
        ten profil, który zaplanowała biblioteka.

        :param vx: przód (``world=True``: globalna X)
        :param vy: lewo (``world=True``: globalna Y)
        :param v_up: pion (cm/s)
        :param yaw_rate: obrót (°/s, dodatni = w prawo)
        :param world: ``vx``/``vy`` są w układzie globalnym - wtedy nie obracamy
            ich ponownie (planer biblioteki już to zrobił)
        :param yaw: kurs nosa z planu na początku próbki (°). Plan bywa zaczyna
            się od innego kursu niż bieżący (np. ``orbit`` ustawia nos w środek
            okręgu) - wtedy różnicę dowracamy na początku kroku.
        """
        self.require_airborne("send_rc_control")
        if seconds <= 0:
            self.commit(event)
            return
        if yaw is not None:
            delta = ((yaw + 180.0) % 360.0) - 180.0 - self.yaw
            delta = ((delta + 180.0) % 360.0) - 180.0
            if abs(delta) > 0.5:
                # plan zakłada inny kurs wyjściowy - obracamy w miejscu na starcie
                yaw_rate += delta / seconds
        if not any((vx, vy, v_up, yaw_rate)):
            self.advance(seconds)
            self.commit(event)
            return
        if world:
            self.integrate_world(event, vx, vy, v_up, yaw_rate, seconds)
        else:
            self.integrate_rc(event, vx, vy, v_up, yaw_rate, seconds)


    @staticmethod
    def _maneuver_label(command: str, args: Sequence[Any]) -> Optional[str]:
        """Czy zdarzenie jest etykietą manewru (start/koniec) - zwróć jego nazwę."""
        if command != "annotate" or not args:
            return None
        label = str(args[0])
        for prefix in ("start: ", "end: "):
            if label.startswith(prefix):
                return label[len(prefix):]
        return label

    # ---------------------------------------------------------------- eksport
    def to_flight_data(self) -> FlightData:
        """Zserializuj lot (telemetria, zdarzenia, ostrzeżenia, ślady ruchu)."""
        events = [e.as_dict() for e in self.recorder.events]
        segments = [span.motion.as_dict(span.t0, span.t1)
                    for span in self.recorder.spans if span.motion is not None]
        # grupuj manewry: zdarzenia między "start: X" i "end: X" dostają maneuver=X
        active: List[str] = []
        for event in events:
            label = self._maneuver_label(event["command"], event["args"])
            if label is not None:
                if str(event["args"][0]).startswith("end:"):
                    if active and active[-1] == label:
                        active.pop()
                else:
                    active.append(label)
                event["maneuver_role"] = "end" if str(event["args"][0]).startswith("end:") else "start"
            if active:
                event["maneuver"] = active[-1]
        return FlightData(
            duration=round(self.now, 4),
            samples=[s.as_dict() for s in self.recorder.samples],
            events=events,
            warnings=list(self.recorder.warnings),
            errors=list(self.recorder.errors),
            segments=segments,
            stats=self.stats(),
            final_state=self.state,
        )

