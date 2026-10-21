"""Klasa ``Pilot`` - publiczne API biblioteki dronemoves.

``Pilot`` zna aktualną (szacowaną) pozycję i yaw drona w układzie startu
(metryka lokalna), planuje manewry i odtwarza je przez executor. Dron sterowany
jest wyłącznie przez backend (``MotionBackend``), więc ten sam kod działa
z mockiem symulatora i z prawdziwym Tello.

Bezpieczeństwo:

* kontekst ``with``: przy wyjątku/Ctrl+C wysyła ``rc(0,0,0,0)``, a potem
  (jeśli ``land_on_exit``) bezpiecznie ląduje,
* ``max_height_cm`` i ``max_radius_cm`` - twarde limity pozycji,
* ``min_battery`` - sprawdzenie baterii przed manewrem,
* RC co 50 ms (20 Hz) - dron nie wyląduje sam z braku komend.
"""

from __future__ import annotations

import math
import threading
from typing import Any, List, Optional, Sequence, Union

from .backends.base import MotionBackend
from .calibration import CalibrationProfile, TELLO_PROFILE, load_profile
from .executor import CONTROL_HZ, Executor
from .planner import (PlanLimits, plan_circle, plan_figure_eight, plan_line, plan_orbit,
                      plan_path, plan_slalom, plan_spiral, plan_turn)
from .trajectory import Sample, Trajectory

__all__ = ["Pilot", "Maneuver", "ManeuverCollection", "SafetyError", "ManeuverError"]

ManeuverLike = Union["Maneuver", Trajectory, Sequence["ManeuverLike"]]


class SafetyError(RuntimeError):
    """Naruszenie limitu bezpieczeństwa (wysokość, promień, bateria)."""


class ManeuverError(RuntimeError):
    """Błąd wykonania manewru."""


class Maneuver:
    """Opis manewru (nazwa + planer + etykieta) - składa się w ``sequence``."""

    def __init__(self, name: str, planner, label: Optional[str] = None, **params: Any) -> None:
        self.name = name
        self.planner = planner
        self.label = label or name
        self.params = params

    def __repr__(self) -> str:  # pragma: no cover - diagnostyka
        return f"Maneuver({self.name!r}, label={self.label!r})"


def _transform(segment: Trajectory, origin: tuple, yaw0: float) -> None:
    """Przenieś segment (liczony od własnego startu z yaw=0) w układ globalny lotu."""
    dx, dy, dz = origin
    rad = math.radians(yaw0)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    for s in segment.samples:
        gx = dx + s.x * cos_a - s.y * sin_a
        gy = dy + s.x * sin_a + s.y * cos_a
        s.x, s.y, s.z = gx, gy, dz + s.z
        s.vx, s.vy = s.vx * cos_a - s.vy * sin_a, s.vx * sin_a + s.vy * cos_a
        s.yaw = (yaw0 + s.yaw) % 360


def _segments_to_trajectory(segments: List[Trajectory], label: str) -> Trajectory:
    """Sklej trajektorie w jedną oś czasu (segmenty muszą być już w układzie globalnym)."""
    from .trajectory import Sample

    samples: List[Sample] = []
    offset = 0.0
    mode = segments[0].mode if segments else "rc"
    for segment in segments:
        for s in segment.samples:
            samples.append(Sample(
                t=s.t + offset, x=s.x, y=s.y, z=s.z, yaw=s.yaw,
                vx=s.vx, vy=s.vy, vz=s.vz, yaw_rate=s.yaw_rate, rc=s.rc,
            ))
        if segment.samples:
            offset = samples[-1].t
    return Trajectory(samples=samples, label=label, mode=mode)


class ManeuverCollection:
    """Fabryka obiektów ``Maneuver`` do składania sekwencji (``p.m.forward(...)``)."""

    def __init__(self, pilot: "Pilot") -> None:
        self.pilot = pilot

    def forward(self, distance_cm: float) -> Maneuver:
        """Manewr: prosty ruch do przodu o ``distance_cm``."""
        distance = abs(float(distance_cm))
        return Maneuver("forward", self.pilot._line_planner(distance),
                        label=f"forward {distance:.0f}cm")

    def turn(self, angle_deg: float, radius: float = 80.0) -> Maneuver:
        """Manewr: zakręt łukiem o ``angle_deg`` i promieniu ``radius``."""
        label = f"turn {angle_deg:.0f}° r={radius:.0f}"
        return Maneuver("turn", self.pilot._turn_planner(angle_deg, radius), label=label)

    def arc(self, angle_deg: float, radius: float = 100.0,
            direction: Optional[str] = None) -> Maneuver:
        """Manewr: łuk o ``angle_deg`` (opcjonalnie wymuszona strona)."""
        side = {"left": 1, "right": -1}.get(direction or "", 0)
        label = f"arc {angle_deg:.0f}° r={radius:.0f}"
        return Maneuver("arc", self.pilot._turn_planner(angle_deg, radius, side),
                        label=label)

    def circle(self, radius: float = 100.0, direction: str = "right",
               face: str = "tangent") -> Maneuver:
        """Manewr: pełne okrążenie o promieniu ``radius``."""
        label = f"circle r={radius:.0f}"
        return Maneuver("circle", self.pilot._circle_planner(radius, direction, face),
                        label=label)

    def orbit(self, radius: float = 120.0, turns: float = 1.0,
              direction: str = "right") -> Maneuver:
        """Manewr: krążenie z nosem do środka."""
        label = f"orbit r={radius:.0f} turns={turns:g}"
        return Maneuver("orbit", self.pilot._orbit_planner(radius, turns, direction),
                        label=label)

    def slalom(self, gates: int = 4, spacing: float = 100.0, width: float = 60.0) -> Maneuver:
        """Manewr: slalom między bramkami."""
        label = f"slalom {gates} bramek"
        return Maneuver("slalom", self.pilot._slalom_planner(gates, spacing, width),
                        label=label)

    def figure_eight(self, radius: float = 80.0) -> Maneuver:
        """Manewr: ósemka o promieniu ``radius``."""
        label = f"figure_eight r={radius:.0f}"
        return Maneuver("figure_eight", self.pilot._eight_planner(radius), label=label)

    def spiral(self, radius: float = 100.0, height: float = 100.0,
               turns: float = 2.0) -> Maneuver:
        """Manewr: wznoszenie po spirali."""
        label = f"spiral r={radius:.0f} h={height:.0f}"
        return Maneuver("spiral", self.pilot._spiral_planner(radius, height, turns),
                        label=label)

    def path(self, points: Sequence[tuple], smooth: bool = True) -> Maneuver:
        """Manewr: przelot przez punkty względne."""
        label = f"path {len(points)} pkt"
        return Maneuver("path", self.pilot._path_planner(points, smooth), label=label)


class Pilot:
    """Wysokopoziomowe sterowanie dronem płynnymi manewrami.

    :param drone: obiekt drona (``djitellopy.Tello`` lub mock symulatora)
    :param backend: własny ``MotionBackend`` (alternatywa dla ``drone``)
    :param speed: prędkość manewrów [cm/s]
    :param profile: profil kalibracji RC (domyślnie Tello)
    :param profile_path: ścieżka JSON z profilem (nadpisuje ``profile``)
    :param max_height_cm: twardy limit wysokości nad ziemią
    :param max_radius_cm: twardy limit oddalenia od punktu startu
    :param min_battery: minimalna bateria [%] przed manewrem
    :param land_on_exit: lądowanie przy wyjściu z kontekstu **po wyjątku**
        (normalne wyjście zostawia sterowanie skryptowi)
    :param frequency_hz: częstotliwość wysyłania RC (domyślnie 20 Hz)
    :param sim_exact: **tylko diagnostyka w symulatorze.** Gdy ``True``, a dron
        udostępnia ``send_dronemoves_profile`` (mock symulatora), executor wysyła
        mu prędkości z planu wprost, zamiast wychyleń RC. Domyślnie ``False`` -
        symulator testuje wtedy dokładnie tę ścieżkę, co prawdziwy Tello
        (``send_rc_control`` z wychyleniami RC).
    """

    def __init__(self, drone: Any = None, *, backend: Optional[MotionBackend] = None,
                 speed: float = 40.0, profile: Optional[CalibrationProfile] = None,
                 profile_path: Optional[str] = None,
                 max_height_cm: float = 300.0, max_radius_cm: float = 500.0,
                 min_battery: int = 20, min_height_cm: float = 30.0,
                 land_on_exit: bool = True, frequency_hz: float = CONTROL_HZ,
                 sim_exact: bool = False) -> None:
        if drone is None and backend is None:
            raise ValueError("Pilot wymaga obiektu drona (drone=...) albo backend=...")
        if backend is None:
            from .backends.tello import backend_for

            backend = backend_for(drone)
        self.drone = drone
        self.backend = backend
        if profile_path:
            profile = load_profile(profile_path)
        self.profile = profile or TELLO_PROFILE
        self.speed = float(speed)
        if self.speed <= 0:
            raise ValueError("speed musi być dodatnie")
        self.limits = PlanLimits(
            min_height_cm=min_height_cm,
            max_height_cm=max_height_cm,
            max_radius_from_start_cm=max_radius_cm,
        )
        self.min_battery = int(min_battery)
        self.land_on_exit = land_on_exit
        self.executor = Executor(backend, frequency_hz=frequency_hz, profile=self.profile,
                                 sim_exact=sim_exact)

        # szacowana pozycja/yaw w układzie startu lotu (metryka lokalna)
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.yaw = 0.0
        self._home_z = self._read_height() or 0.0
        self._in_context = False
        self._lock = threading.Lock()
        #: czas lotu zrealizowany przez pilota [s] (do planu w symulatorze)
        self.flight_time = 0.0

    # ------------------------------------------------------------------ stan
    def _read_height(self) -> Optional[float]:
        try:
            value = self.backend.get_height()
        except Exception:
            return None
        return None if value is None else float(value)

    def _read_battery(self) -> Optional[int]:
        try:
            return self.backend.get_battery()
        except Exception:
            return None

    def position(self) -> tuple:
        """Szacowana pozycja (x, y, z) w układzie startu [cm]."""
        return (self.x, self.y, self.z)

    def ground_height(self) -> float:
        """Wysokość nad ziemią [cm] (wysokość drona odczytana przy starcie + zmiana)."""
        return self._home_z + self.z


    # ------------------------------------------------------- kontekst / awarie
    def __enter__(self) -> "Pilot":
        self._in_context = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._in_context = False
        try:
            self.emergency_stop()
        finally:
            # lądujemy tylko przy błędzie/przerwaniu - normalne wyjście zostawia
            # sterowanie skryptowi (np. wzniesienie, kolejne manewry, t.land())
            if exc_type is not None and self.land_on_exit:
                self._safe_land()
        return False  # nie połykamy wyjątku

    def emergency_stop(self) -> None:
        """Natychmiast ``rc(0,0,0,0)`` - bezpieczne zatrzymanie ruchu."""
        try:
            self.executor.stop()
            self.backend.stop()
        except Exception:
            pass

    def _safe_land(self) -> None:
        land = getattr(self.drone, "land", None) if self.drone is not None else None
        if callable(land):
            try:
                land()
            except Exception:
                pass

    # ------------------------------------------------------------ planowanie
    def _check_battery(self, label: str, duration_hint: float) -> None:
        battery = self._read_battery()
        if battery is not None and battery < self.min_battery:
            raise SafetyError(
                f"Bateria {battery}% jest poniżej progu {self.min_battery}% "
                f"wymaganego przed manewrem '{label}'."
            )

    def _check_floor(self) -> None:
        height = self._read_height()
        if height is not None and height < self.limits.min_height_cm * 0.5:
            raise SafetyError(
                f"Dron jest na {height:.0f} cm - wykonaj takeoff() i wzniesienie "
                f"(manewry wymagają min. {self.limits.min_height_cm:.0f} cm)."
            )

    def preview(self, maneuver: "ManeuverLike") -> List[tuple]:
        """Zwróć zaprojektowaną trajektorię (lista punktów x, y, z) bez lotu."""
        traj = self._plan(maneuver)
        self._record_plan(traj)
        return [(round(s.x, 2), round(s.y, 2), round(s.z, 2)) for s in traj.samples]

    def _record_plan(self, traj: Trajectory) -> None:
        """Dopisz plan do symulatora (na prawdziwym dronie: brak efektu)."""
        try:
            from .simhook import record_preview

            step = max(1, len(traj.samples) // 1500)
            # czas planu w układzie lotu: zegar pilota + czas w obrębie trajektorii
            base = self.flight_time
            entries = [((s.x, s.y, s.z), base + s.t, traj.label) for s in traj.samples[::step]]
            record_preview(self.drone, entries)
        except Exception:
            # plan jest tylko dla wizualizacji - nigdy nie przerywa lotu
            pass

    def preview_trajectory(self, maneuver: "ManeuverLike") -> Trajectory:
        """Jak ``preview``, ale zwraca pełną ``Trajectory`` (z RC i czasem)."""
        return self._plan(maneuver)


    def _plan(self, maneuver: "ManeuverLike") -> Trajectory:
        """Zbuduj trajektorię manewru (lub sekwencji) w układzie lotu, bez ruchu."""
        if isinstance(maneuver, Trajectory):
            return maneuver
        if isinstance(maneuver, (list, tuple)):
            items = list(maneuver)
            if not items:
                return Trajectory(label="sekwencja")
            return self._plan_sequence(items)
        if not isinstance(maneuver, Maneuver):
            raise TypeError("Oczekiwano Maneuver, Trajectory albo listy manewrów")
        plan = maneuver.planner(
            limits=self.limits, profile=self.profile, speed=self.speed, **maneuver.params
        )
        # przenieś plan (liczony od bieżącej pozycji, yaw=0) do układu lotu
        _transform(plan, (self.x, self.y, self.z), self.yaw)
        return plan

    def _plan_sequence(self, items: List["ManeuverLike"]) -> Trajectory:
        """Zaplanuj sekwencję: każdy segment liczony od końca poprzedniego."""
        segments: List[Trajectory] = []
        x, y, z, yaw = self.x, self.y, self.z, self.yaw
        for item in items:
            if isinstance(item, Trajectory):
                plan = item
            else:
                plan = item.planner(limits=self.limits, profile=self.profile,
                                    speed=self.speed, **item.params)
            _transform(plan, (x, y, z), yaw)
            segments.append(plan)
            last = plan.samples[-1]
            x, y, z, yaw = last.x, last.y, last.z, last.yaw
            name = item.label if isinstance(item, Trajectory) else item.name
            self._check_radius(x, y, name)
        return _segments_to_trajectory(segments, "sekwencja")

    def _check_radius(self, x: float, y: float, label: str) -> None:
        radius = math.hypot(x, y)
        if radius > self.limits.max_radius_from_start_cm + 1e-6:
            raise SafetyError(
                f"Po manewrze '{label}' dron byłby {radius:.0f} cm od startu "
                f"(limit {self.limits.max_radius_from_start_cm:.0f} cm)."
            )

    # ------------------------------------------------------------- wykonanie
    def _execute(self, maneuver: "ManeuverLike", label: str) -> Trajectory:
        """Zaplanuj i wykonaj manewr, aktualizując pozycję; zwróć trajektorię."""
        with self._lock:
            self._check_floor()
            traj = self._plan(maneuver)
            if not traj.samples:  # np. pusta sekwencja - nic do wykonania
                return traj
            self._check_battery(label, traj.duration)
            self._check_radius(traj.samples[-1].x, traj.samples[-1].y, label)
            self._record_plan(traj)
            self.backend.annotate(f"start: {label}")
            try:
                self.executor.execute(traj)
            except BaseException:
                self.emergency_stop()
                raise
            finally:
                self.backend.annotate(f"end: {label}")
            last = traj.samples[-1]
            self.x, self.y, self.z, self.yaw = last.x, last.y, last.z, last.yaw % 360.0
            self.flight_time += traj.duration
            return traj

    def run(self, maneuver: "ManeuverLike", label: Optional[str] = None) -> Trajectory:
        """Wykonaj dowolny manewr (obiekt, sekwencję lub gotową trajektorię)."""
        name = label or getattr(maneuver, "name", None) or "manewr"
        return self._execute(maneuver, name)


    # ------------------------------------------------------------- manewry
    def forward(self, distance_cm: float, mode: str = "rc") -> Trajectory:
        """Płynny ruch prosto do przodu o ``distance_cm`` (rozpędzanie/hamowanie)."""
        distance = abs(float(distance_cm))
        maneuver = Maneuver("forward", self._line_planner(distance),
                            label=f"forward {distance:.0f}cm")
        return self._execute_mode(maneuver, maneuver.label, mode)

    def turn(self, angle_deg: float, radius: float = 80.0, mode: str = "rc") -> Trajectory:
        """Płynny zakręt łukiem; nos podąża za torem (ujemny kąt = w prawo)."""
        label = f"turn {angle_deg:.0f}° r={radius:.0f}"
        maneuver = Maneuver("turn", self._turn_planner(angle_deg, radius), label=label)
        return self._execute_mode(maneuver, label, mode)

    def arc(self, angle_deg: float, radius: float = 100.0, mode: str = "rc",
            direction: Optional[str] = None) -> Trajectory:
        """Łuk o zadanym kącie; ``direction`` (``left``/``right``) wymusza stronę."""
        side = {"left": 1, "right": -1}.get(direction or "", 0)
        label = f"arc {angle_deg:.0f}° r={radius:.0f}"
        maneuver = Maneuver("arc", self._turn_planner(angle_deg, radius, side), label=label)
        return self._execute_mode(maneuver, label, mode)

    def circle(self, radius: float = 100.0, direction: str = "right",
               face: str = "tangent", mode: str = "rc") -> Trajectory:
        """Pełne okrążenie; ``face``: ``tangent`` (nos po torze), ``center``, ``fixed``."""
        label = f"circle r={radius:.0f}"
        maneuver = Maneuver("circle", self._circle_planner(radius, direction, face),
                            label=label)
        return self._execute_mode(maneuver, label, mode)

    def hover(self, seconds: float) -> Trajectory:
        """Zawiśnij w miejscu przez ``seconds`` (RC 0, ale komendy co 50 ms)."""
        if seconds <= 0:
            raise ValueError("seconds musi być dodatnie")
        label = f"hover {seconds:.1f}s"
        maneuver = Maneuver("hover", self._hover_planner(seconds), label=label)
        return self._execute(maneuver, label)

    def sequence(self, maneuvers: Sequence["ManeuverLike"]) -> Trajectory:
        """Wykonaj listę manewrów jako jeden płynny ruch (bez zatrzymań)."""
        return self._execute(list(maneuvers), "sekwencja")

    # ---------------------------------------------- manewry do sekwencji
    def maneuvers(self) -> "ManeuverCollection":
        """Obiekty manewrów do złożenia w ``sequence`` (bez natychmiastowego lotu).

        .. code-block:: python

            p.sequence([p.maneuvers().forward(100), p.maneuvers().turn(90, radius=80)])
        """
        return ManeuverCollection(self)

    def orbit(self, radius: float = 120.0, turns: float = 1.0,
              direction: str = "right", mode: str = "rc") -> Trajectory:
        """Krążenie wokół punktu z nosem zawsze skierowanym do środka."""
        label = f"orbit r={radius:.0f} turns={turns:g}"
        return self._execute_mode(Maneuver("orbit", self._orbit_planner(radius, turns, direction),
                                           label=label), label, mode)

    def slalom(self, gates: int = 4, spacing: float = 100.0, width: float = 60.0,
               mode: str = "rc") -> Trajectory:
        """Slalom między bramkami (przechodzi przez środki bramek)."""
        label = f"slalom {gates} bramek"
        return self._execute_mode(Maneuver("slalom", self._slalom_planner(gates, spacing, width),
                                           label=label), label, mode)

    def figure_eight(self, radius: float = 80.0, mode: str = "rc") -> Trajectory:
        """Ósemka - dwa łuki w przeciwne strony, powrót do punktu startu."""
        label = f"figure_eight r={radius:.0f}"
        return self._execute_mode(Maneuver("figure_eight", self._eight_planner(radius),
                                           label=label), label, mode)

    def spiral(self, radius: float = 100.0, height: float = 100.0, turns: float = 2.0,
               mode: str = "rc") -> Trajectory:
        """Wznoszenie po spirali (stały promień, rosnąca wysokość)."""
        label = f"spiral r={radius:.0f} h={height:.0f}"
        return self._execute_mode(Maneuver("spiral", self._spiral_planner(radius, height, turns),
                                           label=label), label, mode)

    def path(self, points: Sequence[tuple], smooth: bool = True,
             mode: str = "rc") -> Trajectory:
        """Przelot przez punkty względne ``[(x, y, z), ...]`` (spline albo łamana).

        Pierwszy punkt bywa oddalony od drona (np. ``(80, 0, 0)``) - trajektoria
        zaczyna się wtedy w punkcie ``(0, 0, z)`` (miejsce, gdzie dron jest),
        żeby plan nie „teleportował” drona na start trasy.
        """
        label = f"path {len(points)} pkt"
        first = tuple(float(v) for v in points[0])
        start_z = first[2] if len(first) > 2 else 0.0
        route = list(points)
        if len(points) > 1 and (abs(first[0]) > 0.5 or abs(first[1]) > 0.5):
            route = [(0.0, 0.0, start_z)] + [tuple(float(v) for v in p) for p in points]
        return self._execute_mode(Maneuver("path", self._path_planner(route, smooth),
                                           label=label), label, mode)

    # ------------------------------------------------------- planery (domknięcia)
    def _line_planner(self, distance_cm: float):
        def planner(*, limits, profile, speed):
            return plan_line(distance_cm, limits=limits, profile=profile, speed=speed,
                             label=f"forward {distance_cm:.0f}cm")
        return planner

    def _turn_planner(self, angle_deg: float, radius: float, side: int = 0):
        def planner(*, limits, profile, speed):
            return plan_turn(angle_deg, radius, side=side, limits=limits, profile=profile,
                             speed=speed, label=f"turn {angle_deg:.0f}° r={radius:.0f}")
        return planner

    def _circle_planner(self, radius: float, direction: str, face: str):
        def planner(*, limits, profile, speed):
            return plan_circle(radius, direction=direction, face=face, limits=limits,
                               profile=profile, speed=speed,
                               label=f"circle r={radius:.0f} {direction}")
        return planner

    def _hover_planner(self, seconds: float):
        def planner(*, limits, profile, speed):
            traj = Trajectory(label=f"hover {seconds:.1f}s")
            steps = max(1, int(round(seconds / limits.dt)))
            for i in range(steps + 1):
                traj.samples.append(Sample(t=i * limits.dt, x=0.0, y=0.0, z=0.0, yaw=0.0))
            return traj.with_rc(profile)
        return planner

    def _orbit_planner(self, radius: float, turns: float, direction: str):
        def planner(*, limits, profile, speed):
            return plan_orbit(radius, turns, direction=direction, limits=limits,
                              profile=profile, speed=speed)
        return planner

    def _slalom_planner(self, gates: int, spacing: float, width: float):
        def planner(*, limits, profile, speed):
            return plan_slalom(gates, spacing, width, limits=limits, profile=profile,
                               speed=speed)
        return planner

    def _eight_planner(self, radius: float):
        def planner(*, limits, profile, speed):
            return plan_figure_eight(radius, limits=limits, profile=profile, speed=speed)
        return planner

    def _spiral_planner(self, radius: float, height: float, turns: float):
        def planner(*, limits, profile, speed):
            return plan_spiral(radius, height, turns, limits=limits, profile=profile,
                               speed=speed)
        return planner

    def _path_planner(self, points: Sequence[tuple], smooth: bool):
        def planner(*, limits, profile, speed):
            return plan_path(points, smooth=smooth, limits=limits, profile=profile,
                             speed=speed)
        return planner

    # ------------------------------------------------------- tryby rc / native
    def _execute_mode(self, maneuver: "ManeuverLike", label: str, mode: str) -> Trajectory:
        if mode not in ("rc", "native"):
            raise ValueError("mode musi być 'rc' albo 'native'")
        if mode == "native" and not self.backend.supports_native():
            raise NotImplementedError(
                f"Backend {self.backend.name!r} nie obsługuje trybu native "
                "(wymaga curve_xyz_speed / go_xyz_speed)."
            )
        return self._execute(maneuver, label)

