"""Sesja „Lotu ręcznego”: dron sterowany na żywo przez RC + nagrywanie.

Dlaczego po stronie serwera, a nie w przeglądarce: fizyka musi być **ta sama**
co w symulacji skryptów (inaczej nagranie nie odtworzy się tak samo). Tutaj
używamy dokładnie tych samych klas co sandbox: :class:`app.sim.core.Simulation`
i :meth:`Simulation.rc_motion`, więc wychylenia RC, profil kalibracji, obroty
i kolizje liczą się identycznie jak w ``send_rc_control`` w skrypcie.

Konwencja RC (jak w djitellopy/Tello, ``rc a b c d``):

* ``lr``  - w prawo dodatnie, w lewo ujemne,
* ``fb``  - przód dodatni, tył ujemny,
* ``ud``  - góra dodatnia, dół ujemny,
* ``yaw`` - **obrót w prawo dodatni** (zgodnie z zegarem, rośnie ``get_yaw()``).

Czas: przeglądarka wysyła ``dt`` (sekundy, które upłynęły od poprzedniego
odświeżenia). ``dt`` jest ograniczany (:data:`MAX_DT_S`), żeby jedna zawieszona
klatka nie przeniosła drona o kilka metrów.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...sim import core

#: największy krok czasu przyjmowany od klienta [s] - chroni przed skokiem
#: drona po zgubionej klatce (przy 50 cm/s to najwyżej 15 cm ruchu)
MAX_DT_S = 0.3
#: minimalny krok czasu, żeby serię szybkich odświeżeń nie dzielić na mikro-kroki
MIN_DT_S = 0.01
#: zakres prędkości (wychylenie RC przy pełnym wciśnięciu klawisza)
SPEED_MIN, SPEED_MAX = 10, 100
#: domyślny margines ostrzeżenia o zbliżeniu do przeszkody [cm]
DEFAULT_MARGIN_CM = 20.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_rc(value: Any) -> int:
    """Wychylenie RC jako liczba całkowita z zakresu -100..100."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return int(_clamp(number, -100, 100))


class ManualSession:
    """Stan jednego „Lotu ręcznego”: symulacja, nagranie i ostrzeżenia.

    Sesja jest niezależna od uruchomień skryptów - ma własny
    :class:`~app.sim.core.Simulation`, więc lot ręczny nie koliduje
    z uruchomionym skryptem ani z zapisanymi lotami.
    """

    def __init__(self, speed: int = 50, scene: Optional[Dict[str, Any]] = None,
                 margin_cm: float = DEFAULT_MARGIN_CM) -> None:
        self.settings = core.Settings()
        self.sim = core.Simulation(self.settings)
        self.speed = int(_clamp(int(speed or 50), SPEED_MIN, SPEED_MAX))
        self.margin_cm = float(margin_cm)
        #: scena przeszkód do ostrzeżeń na żywo (``None`` = brak kontroli)
        self.scene: Optional[Any] = None
        if scene:
            try:
                from ..obstacles.model import Scene

                self.scene = Scene.from_dict(scene)
            except Exception:                     # noqa: BLE001 - zła scena nie psuje sesji
                self.scene = None
        self._lock = threading.RLock()
        #: nagranie: kolejne odcinki RC ``{t, dt, lr, fb, ud, yaw}``
        self.recording: List[Dict[str, float]] = []
        self.record_enabled = True
        self.takeoff_t: Optional[float] = None
        self.land_t: Optional[float] = None
        self.warnings: List[str] = []
        self._last_warning: Optional[str] = None

    # ------------------------------------------------------------------ stan
    @property
    def flying(self) -> bool:
        return self.sim.airborne

    def _event(self, command: str, args: Sequence[Any]) -> core.Event:
        event, _file, _line = self.sim.begin(command, args)
        return event

    def clearance(self) -> Optional[float]:
        """Najmniejszy odstęp od przeszkód [cm] (``None`` = brak sceny)."""
        if self.scene is None:
            return None
        from ..obstacles.collisions import clearance_to_obstacle

        position = tuple(self.sim.position)
        best = math.inf
        for obstacle in self.scene.solids():
            best = min(best, clearance_to_obstacle(position, self.sim.yaw, obstacle))
        return None if best is math.inf else best

    def state(self) -> Dict[str, Any]:
        """Bieżący stan do wyświetlenia w UI (bez historii)."""
        x, y, z = self.sim.position
        clearance = self.clearance()
        warning = None
        if clearance is not None:
            if clearance < 0:
                warning = "KOLIZJA - dron dotyka przeszkody"
            elif clearance <= self.margin_cm:
                warning = f"Blisko przeszkody: {clearance:.0f} cm"
        if warning and warning != self._last_warning:
            self.warnings.append(f"t={self.sim.now:.1f}s {warning}")
        self._last_warning = warning
        return {
            "flying": self.flying,
            "x": round(x, 1), "y": round(y, 1), "z": round(z, 1),
            "yaw": round((-self.sim.yaw) % 360.0, 1),      # konwencja get_yaw
            "yaw_internal": round(self.sim.yaw, 2),
            "t": round(self.sim.now, 2),
            "battery": round(self.sim.battery, 1),
            "speed": self.speed,
            "clearance": None if clearance is None else round(clearance, 1),
            "warning": warning,
            "recording": self.record_enabled,
            "recorded_segments": len(self.recording),
            "state": self.sim.state,
        }

    # --------------------------------------------------------------- sterowanie
    def start(self) -> Dict[str, Any]:
        """Start (``takeoff``) - dron wznosi się na 80 cm."""
        with self._lock:
            if self.flying:
                return self.state()
            event = self._event("takeoff", [])
            self.sim.takeoff(event)
            self.takeoff_t = self.sim.now
            return self.state()

    def rc(self, lr: Any = 0, fb: Any = 0, ud: Any = 0, yaw: Any = 0,
           dt: Any = MAX_DT_S) -> Dict[str, Any]:
        """Wykonaj odcinek RC trwający ``dt`` sekund (maks. :data:`MAX_DT_S`)."""
        with self._lock:
            lr, fb, ud, yaw = (_as_rc(lr), _as_rc(fb), _as_rc(ud), _as_rc(yaw))
            try:
                seconds = float(dt)
            except (TypeError, ValueError):
                seconds = 0.0
            seconds = _clamp(seconds, 0.0, MAX_DT_S)
            if seconds < MIN_DT_S:
                return self.state()
            if not self.flying:
                # RC na ziemi nic nie robi (jak w symulatorze skryptów)
                self.sim.advance(seconds)
                return self.state()
            event = self._event("send_rc_control", [lr, fb, ud, yaw, round(seconds, 3)])
            self.sim.rc_motion(event, lr, fb, ud, yaw, seconds)
            if self.record_enabled:
                self.recording.append({"t": round(self.sim.now - seconds, 3),
                                       "dt": round(seconds, 3), "lr": lr, "fb": fb,
                                       "ud": ud, "yaw": yaw})
            return self.state()

    def land(self) -> Dict[str, Any]:
        """Lądowanie (opadanie pionowe do 0)."""
        with self._lock:
            if not self.flying:
                return self.state()
            event = self._event("land", [])
            self.sim.land(event)
            self.land_t = self.sim.now
            return self.state()

    def set_speed(self, speed: Any) -> Dict[str, Any]:
        """Ustaw prędkość manewrową (zakres 10-100, jak ``set_speed`` w Tello)."""
        with self._lock:
            try:
                value = int(round(float(speed)))
            except (TypeError, ValueError):
                value = self.speed
            self.speed = int(_clamp(value, SPEED_MIN, SPEED_MAX))
            return self.state()

    def set_recording(self, enabled: Any) -> Dict[str, Any]:
        """Włącz/wyłącz nagrywanie (wyłączenie nie kasuje nagrania)."""
        with self._lock:
            self.record_enabled = bool(enabled)
            return self.state()

    # ----------------------------------------------------------------- nagranie
    def flight_data(self):
        """Telemetria sesji w formacie lotu symulatora (do porównań i wykresów)."""
        with self._lock:
            return self.sim.to_flight_data()

    def control_points(self) -> List[Tuple[float, float, float, float]]:
        """Punkty kontrolne nagrania: ``(t, x, y, z)`` przy każdej zmianie RC.

        To momenty, w których wychylenia się zmieniają (albo dron się zatrzymuje)
        - porównanie „nagranie vs wygenerowany skrypt" odbywa się właśnie w tych
        punktach.
        """
        samples = self.sim.to_flight_data().samples
        if not samples or not self.recording:
            return []
        moments: List[float] = []
        previous: Optional[Tuple[int, int, int, int]] = None
        for index, segment in enumerate(self.recording):
            current = (segment["lr"], segment["fb"], segment["ud"], segment["yaw"])
            if previous is None:
                moments.append(segment["t"])
            elif current != previous:
                # koniec poprzedniego odcinka = początek nowego
                moments.append(segment["t"])
            previous = current
        last = self.recording[-1]
        moments.append(last["t"] + last["dt"])
        return [(moment, *_at(samples, moment)) for moment in sorted(set(moments))]

    def stop_points(self) -> List[Tuple[float, float, float, float]]:
        """Punkty zatrzymań: ``(t, x, y, z)`` po odcinku z zerowym RC."""
        samples = self.sim.to_flight_data().samples
        points: List[Tuple[float, float, float, float]] = []
        for segment in self.recording:
            if any((segment["lr"], segment["fb"], segment["ud"], segment["yaw"])):
                continue
            moment = segment["t"] + segment["dt"]
            points.append((moment, *_at(samples, moment)))
        return points


def _at(samples: Sequence[Dict[str, Any]], moment: float) -> Tuple[float, float, float]:
    """Pozycja ``(x, y, z)`` z telemetrii najbliżej chwili ``moment``."""
    if not samples:
        return (0.0, 0.0, 0.0)
    closest = min(samples, key=lambda sample: abs(sample["t"] - moment))
    return (float(closest["x"]), float(closest["y"]), float(closest["z"]))


# --------------------------------------------------------------- rejestr sesji
_SESSION: Optional[ManualSession] = None
_SESSION_LOCK = threading.RLock()


def current() -> Optional[ManualSession]:
    """Bieżąca sesja lotu ręcznego (``None`` = nie uruchomiona)."""
    with _SESSION_LOCK:
        return _SESSION


def start_session(speed: int = 50, scene: Optional[Dict[str, Any]] = None,
                  margin_cm: float = DEFAULT_MARGIN_CM) -> ManualSession:
    """Utwórz nową sesję (poprzednia jest zastępowana)."""
    global _SESSION
    with _SESSION_LOCK:
        _SESSION = ManualSession(speed=speed, scene=scene, margin_cm=margin_cm)
        return _SESSION


def close_session() -> bool:
    """Zamknij sesję (zwraca ``True``, jeśli jakaś była)."""
    global _SESSION
    with _SESSION_LOCK:
        existed = _SESSION is not None
        _SESSION = None
        return existed
