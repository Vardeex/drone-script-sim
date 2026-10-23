"""Executor: odtwarzanie trajektorii przez ``send_rc_control`` z korektą czasu.

Wysyła wychylenia RC z częstotliwością 20 Hz według planu, ale mierzy
**rzeczywisty** czas (``time.monotonic``) - jeśli pętla się spóźni, przeskakuje
w trajektorii do właściwej chwili zamiast zwalniać. Dzięki temu manewr trwa
tyle, ile zaplanowano, nawet gdy wywołania drona są wolniejsze.

Sterowanie zawsze idzie przez ``send_rc_control`` - dokładnie tak, jak na
prawdziwym Tello. Opcjonalny kanał ``send_profile`` (tylko mock symulatora)
jest wyłączony domyślnie; włącza się go w ``Pilot(..., sim_exact=True)``.

Executyor nie zna drona: dostaje backend (``MotionBackend``).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional

from .backends.base import MotionBackend
from .calibration import CalibrationProfile
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
                 time_fn: Optional[Callable[[], float]] = None,
                 sleep_fn: Optional[Callable[[float], None]] = None,
                 profile: Optional[CalibrationProfile] = None,
                 sim_exact: bool = False) -> None:
        if frequency_hz <= 0:
            raise ValueError("frequency_hz musi być dodatnie")
        self.backend = backend
        self.period = 1.0 / frequency_hz
        #: profil kalibracji - ten sam, którym planer liczy wychylenia RC
        self.profile = profile or CalibrationProfile()
        #: diagnostyczny kanał dokładnych prędkości (mock symulatora); domyślnie OFF
        self.sim_exact = bool(sim_exact)
        # Zegar i sen bierzemy z modułu ``time`` w chwili wywołania, nie z domyślnych
        # argumentów: w symulatorze ``time.sleep``/``time.monotonic`` są podmieniane
        # na zegar wirtualny już po imporcie biblioteki. Dzięki temu pętla RC
        # i symulator dzielą tę samą oś czasu.
        self._time = time_fn or (lambda: time.monotonic())
        self._sleep = sleep_fn or (lambda seconds: time.sleep(seconds))
        self._stop = threading.Event()
        #: wzmocnienie korekty kursu: °/s na 1° błędu (5 °/s na stopień)
        self.yaw_gain = 5.0
        #: maksymalne wydłużenie obrotu w miejscu dla dogrania kursu [s]
        self.rotate_timeout_s = 1.0

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
        #: przyrost czasu na dogranie obrotu w miejscu (gdy błąd kursu > 3°)
        overtime = 0.0
        try:
            while True:
                elapsed = self._time() - started
                if elapsed >= duration + overtime:
                    break
                # korekta czasu: próbka dla faktycznie minionej chwili
                sample = trajectory.at(min(elapsed, duration))
                if not self._send_profile(sample):
                    # Ścieżka prawdziwego drona: prędkości próbki są w układzie
                    # GLOBALNYM, więc rzutujemy je na osie drona według kursu
                    # RZECZYWISTEGO (sprzężenie zwrotne), a kanał yaw dostaje
                    # dodatkowo korektę proporcjonalną do błędu kursu.
                    actual = self._actual_heading()
                    correction = 0.0
                    if actual is not None:
                        error = ((sample.yaw - actual + 180.0) % 360.0) - 180.0
                        correction = max(-self.profile.max_yaw_rate_dps,
                                         min(self.profile.max_yaw_rate_dps,
                                             error * self.yaw_gain))
                        # odcinek obrotu w miejscu: czekaj, aż kurs dojdzie
                        if elapsed >= duration and abs(error) > 3.0:
                            if overtime < self.rotate_timeout_s:
                                overtime += self.period
                        if elapsed >= duration and abs(error) <= 3.0:
                            if overtime:
                                overtime = 0.0
                    lr, fb, ud, yaw = self._rc_for_sample(sample, actual, correction)
                    self.backend.rc(vx=lr, vy=fb, vz=ud, yaw_rate=yaw)
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
            self._send_profile(None)
            self.backend.rc(vx=0, vy=0, vz=0, yaw_rate=0)
            self.backend.stop()
        return ExecuteResult(duration=duration, samples_sent=sent,
                             real_seconds=self._time() - started, stopped=stopped)

    def _actual_heading(self) -> Optional[float]:
        """Rzeczywisty kurs w konwencji planera (CCW+) albo ``None`` (brak odczytu)."""
        reader = getattr(self.backend, "get_yaw", None)
        if not callable(reader):
            return None
        try:
            api_yaw = reader()
        except Exception:
            return None
        if api_yaw is None:
            return None
        # API (CW+) -> CCW+ w zakresie (-180, 180], jak w planerze
        return (-float(api_yaw) + 180.0) % 360.0 - 180.0

    def _rc_for_sample(self, sample, heading: Optional[float] = None,
                       yaw_correction: float = 0.0) -> tuple:
        """Zamień prędkości próbki (globalne) na wychylenia RC dla djitellopy.

        :param heading: **rzeczywisty** kurs drona (CCW+, stopnie) - używany do
            rzutu prędkości globalnych na osie drona; ``None`` = kurs z planu
            (otwarta pętla, np. backend bez ``get_yaw``)
        :param yaw_correction: korekta prędkości obrotu [°/s] (CCW+) dopisana do
            ``yaw_rate`` z planu

        ``sample.vx``/``sample.vy`` są w układzie lotu (globalnym), a ``sample.yaw``
        to kurs nosa. Rzutujemy prędkość na osie drona (przód / prawo) i przeliczamy
        ją na RC **tym samym profilem kalibracji, którym planer liczył plan** - dzięki
        temu wychodzą dokładnie te wartości, które zaplanowano (bez drugiego,
        innego przelicznika).

        Zwraca ``(lr, fb, ud, yaw)`` w kolejności ``rc a b c d`` djitellopy:
        ``lr`` > 0 = **w prawo**, ``yaw`` > 0 = obrót **w prawo** (zgodnie z zegarem,
        tak rośnie ``get_yaw()``).

        Kierunki: ``sample.yaw`` rośnie w lewo (CCW, jak w planie), a ``+Y`` to lewo:
        oś nosa to ``(cos yaw, sin yaw)``, a oś „prawo” to nos obrócony w prawo,
        czyli ``(sin yaw, -cos yaw)`` (dla yaw = 0 daje ``(0, -1)`` = -Y = prawo).
        Dla lotu w -Y przy kursie 270° (CCW) wychodzi więc ``forward = +40``,
        a dla kursu 0° z prędkością w -Y - ``right = +40``.
        """
        # kurs do rzutu: rzeczywisty, gdy znamy (sprzężenie zwrotne), inaczej z planu
        heading = sample.yaw if heading is None else heading
        rad = math.radians(heading)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        # rzut prędkości globalnej na osie drona
        forward = sample.vx * cos_a + sample.vy * sin_a        # przód
        right = sample.vx * sin_a - sample.vy * cos_a          # prawo
        yaw_rate = sample.yaw_rate + yaw_correction            # CCW+
        return (
            self.profile.speed_to_rc(right),
            self.profile.speed_to_rc(forward),
            self.profile.speed_to_rc(sample.vz),
            # planer trzyma kurs CCW+ (dodatni = w lewo), a `yaw` w RC/djitellopy
            # rośnie w prawo (CW+) - na granicy API zmieniamy znak
            self.profile.yaw_rate_to_rc(-yaw_rate),
        )

    def _send_profile(self, sample) -> bool:
        """Diagnostyczny kanał: przekaż prędkości próbki wprost do backendu.

        Działa tylko przy ``sim_exact=True`` i tylko z backendem, który to
        obsługuje (mock symulatora). Domyślnie wyłączony - symulator testuje
        wtedy wyłącznie ścieżkę ``send_rc_control``, tak jak prawdziwy dron.

        ``vx``/``vy`` trajektorii są w układzie **globalnym**, a ``yaw`` to kurs
        nosa - przekazujemy je bez obracania (``world=True``).
        """
        if not self.sim_exact:
            return False
        if sample is None:
            return self.backend.send_profile(0.0, 0.0, 0.0, 0.0, world=True)
        return self.backend.send_profile(sample.vx, sample.vy, sample.vz, sample.yaw_rate,
                                         world=True, yaw_deg=sample.yaw)
