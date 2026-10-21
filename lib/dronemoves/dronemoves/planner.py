"""Planowanie ścieżek manewrów - czysta geometria (bez sterowania dronem).

Każdy generator zwraca ``Trajectory`` (lista ``Sample`` w stałym kroku czasu)
z gładko zmieniającymi się prędkościami. Dzięki temu executor tylko odtwarza
trajektorię, a ``Pilot.preview`` może ją pokazać bez lotu.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

from .calibration import CalibrationProfile
from .trajectory import Sample, Trajectory, smoothstep

__all__ = [
    "PathError", "PlanLimits", "TrajectoryBuilder",
    "plan_line", "plan_turn", "plan_arc", "plan_circle",
    "plan_orbit", "plan_slalom", "plan_figure_eight", "plan_spiral", "plan_path",
]

Point = Tuple[float, float, float]


class PathError(ValueError):
    """Parametry manewru są niewykonalne dla danego profilu kalibracji."""


@dataclass
class PlanLimits:
    """Ograniczenia planera."""

    #: krok trajektorii [s] = częstotliwość pracy executora 20 Hz
    dt: float = 0.05
    #: minimalny promień manewru [cm]
    min_radius_cm: float = 20.0
    #: minimalna wysokość lotu dla manewrów z wznoszeniem [cm]
    min_height_cm: float = 30.0
    #: limit wysokości nad ziemią [cm]
    max_height_cm: float = 300.0
    #: limit oddalenia od punktu startu [cm]
    max_radius_from_start_cm: float = 500.0
    #: limit prędkości obrotu nosa [stopni/s] (zapas wobec limitu profilu)
    max_yaw_rate_dps: float = 60.0


def _arc_len(radius: float, angle_deg: float) -> float:
    """Długość łuku [cm] dla kąta w stopniach."""
    return abs(math.radians(angle_deg)) * radius


def _tra(x: float) -> float:
    return x


class TrajectoryBuilder:
    """Buduje próbki trajektorii z parametryzowanej krzywej.

    Manewr podaje funkcję ``curve(s)``, gdzie ``s`` to przebyta droga w [0, 1],
    zwracającą ``(x, y, z, yaw)`` w układzie drona (pozycja względna do startu,
    yaw w stopniach). Builder dokłada profil prędkości w czasie (trapez),
    liczy prędkości i (opcjonalnie) gotowe próbki RC.
    """

    def __init__(self, limits: PlanLimits, profile: CalibrationProfile) -> None:
        self.limits = limits
        self.profile = profile
        self.samples: List[Sample] = []
        self.t = 0.0
        self.state = (0.0, 0.0, 0.0, 0.0)  # x, y, z, yaw (pozycja bieżąca)

    def curve(self, curve: Callable[[float], Tuple[float, float, float, float]],
              length_cm: float, speed: float, *, kind: str = "trap",
              accel: Optional[float] = None, smooth_yaw: bool = False,
              yaw_window: int = 9) -> None:
        """Dodaj odcinek ruchu po krzywej długości ``length_cm`` z prędkością ``speed``.

        :param curve: ``s`` w [0,1] -> ``(x, y, z, yaw)`` w układzie startowym manewru
        :param length_cm: długość drogi (do wyliczenia czasu i prędkości)
        :param kind: ``trap`` (profil trapezowy) albo ``smooth`` (smoothstep)
        :param smooth_yaw: wygładź kąt nosa w czasie (manewry ze zwrotami)
        """
        if speed <= 0:
            raise PathError("Prędkość manewru musi być dodatnia.")
        accel_v = accel if accel is not None else self.profile.max_accel_cm_s2
        t_acc, t_cruise, t_dec, v_peak, accel_v = _trapezoid_params(length_cm, speed, accel_v)
        duration = max(t_acc + t_cruise + t_dec, 2.0 * self.limits.dt)

        steps = max(2, int(math.ceil(duration / self.limits.dt)))
        dt = duration / steps
        prev = curve(0.0)
        # Gdy odcinek startuje po poprzednim (np. po rotate() w orbit), stan wyjściowy
        # jest już zapisany w próbkach - pierwsza próbka musi wypaść o ``dt`` później,
        # żeby w osi czasu nie było dwóch próbek z tym samym ``t``.
        first_offset = dt if self.samples else 0.0
        for i in range(steps + 1):
            frac = i / steps
            if i > 0:
                self.t += dt
            elif first_offset:
                self.t += first_offset
            if kind == "smooth":
                s = smoothstep(frac)
            else:
                s = _trapezoid_distance(frac * duration, t_acc, t_cruise, t_dec,
                                        v_peak, accel_v)
                s /= length_cm if length_cm > 0 else 1.0
            s = max(0.0, min(1.0, s))
            if i == steps:
                s = 1.0  # ostatnia próbka dokładnie na celu (bez resztek profilu)
            x, y, z, yaw = curve(s)
            vx = (x - prev[0]) / dt
            vy = (y - prev[1]) / dt
            vz = (z - prev[2]) / dt
            dyaw = ((yaw - prev[3] + 540) % 360) - 180
            yaw_rate = dyaw / dt
            self.samples.append(Sample(
                t=self.t, x=x, y=y, z=z, yaw=yaw % 360,
                vx=vx, vy=vy, vz=vz, yaw_rate=yaw_rate,
            ))
            prev = (x, y, z, yaw)
        self.state = prev
        if smooth_yaw:
            Trajectory(samples=self.samples).smooth_yaw(window=yaw_window)

    def rotate(self, angle_deg: float, *, yaw_rate_dps: Optional[float] = None) -> None:
        """Obrót **w miejscu** o ``angle_deg`` (dodatni = w lewo/CCW).

        Manewry zmieniające kurs przed startem (np. ``orbit``) muszą to zrobić
        osobnym odcinkiem: pierwsza próbka planu nie może „przeskoczyć” yaw,
        bo dron nie miałby jak się obrócić.
        """
        if abs(angle_deg) < 1e-9:
            return
        limit = min(self.limits.max_yaw_rate_dps, self.profile.max_yaw_rate_dps)
        rate = min(abs(yaw_rate_dps), limit) if yaw_rate_dps else min(90.0, limit)
        duration = abs(angle_deg) / max(rate, 1e-6)
        steps = max(1, int(math.ceil(duration / self.limits.dt)))
        d_yaw = angle_deg / steps
        dt = duration / steps
        base = self.state[3]
        for i in range(1, steps + 1):
            self.t += dt
            yaw = base + d_yaw * i
            self.samples.append(Sample(
                t=self.t, x=self.state[0], y=self.state[1], z=self.state[2],
                yaw=yaw % 360, vx=0.0, vy=0.0, vz=0.0, yaw_rate=d_yaw / dt,
            ))
        # kurs po odcinku: dokładnie na docelowym kącie (bez dryfu numerycznego)
        self.state = (self.state[0], self.state[1], self.state[2], base + angle_deg)

    def finish(self, label: str, mode: str = "rc", meta: Optional[dict] = None) -> Trajectory:
        """Zamknij trajektorię: dodaj próbki RC z profilu i zwróć ``Trajectory``."""
        traj = Trajectory(samples=self.samples, label=label, mode=mode, meta=dict(meta or {}))
        return traj.with_rc(self.profile)


# --------------------------------------------------------------------- manewry
def plan_line(length_cm: float, *, start_yaw: float = 0.0, limits: PlanLimits,
              profile: CalibrationProfile, speed: float,
              label: str = "forward") -> Trajectory:
    """Ruch prosty do przodu o ``length_cm`` (wzdłuż nosa)."""
    if length_cm <= 0:
        raise PathError("Długość ruchu musi być dodatnia.")
    angle = math.radians(start_yaw)
    builder = TrajectoryBuilder(limits, profile)

    def curve(s: float) -> Tuple[float, float, float, float]:
        return (length_cm * s * math.cos(angle), length_cm * s * math.sin(angle),
                0.0, start_yaw)

    builder.curve(curve, length_cm, speed)
    traj = builder.finish(label)
    _check_limits(traj, limits)
    return traj


def plan_turn(angle_deg: float, radius_cm: float, *, side: int = 0, limits: PlanLimits,
              profile: CalibrationProfile, speed: float,
              label: str = "turn") -> Trajectory:
    """Płynny zakręt łukiem (nos podąża za torem).

    ``side = 0``: strona wynika ze znaku kąta (dodatni = w lewo),
    ``side = +1`` wymusza lewo, ``side = -1`` wymusza prawo.
    """
    if radius_cm < limits.min_radius_cm:
        raise PathError(
            f"Promień {radius_cm:.0f} cm jest za mały (min. {limits.min_radius_cm:.0f} cm). "
            "Zwiększ promień."
        )
    if angle_deg == 0:
        raise PathError("Kąt zakrętu musi być różny od zera.")
    sign = side if side != 0 else (1 if angle_deg > 0 else -1)
    angle = abs(angle_deg) * sign  # dodatni = w lewo
    limit = min(limits.max_yaw_rate_dps, profile.max_yaw_rate_dps)
    required_yaw_rate = math.degrees(speed / radius_cm)
    if required_yaw_rate > limit:
        needed_radius = speed / math.radians(limit)
        max_speed = radius_cm * math.radians(limit)
        raise PathError(
            f"Zakręt r={radius_cm:.0f} cm przy v={speed:.0f} cm/s wymaga obrotu "
            f"{required_yaw_rate:.0f}°/s - limit to {limit:.0f}°/s. "
            f"Zwiększ promień do min. {needed_radius:.0f} cm lub zmniejsz prędkość "
            f"do {max_speed:.0f} cm/s."
        )
    r = radius_cm
    builder = TrajectoryBuilder(limits, profile)

    def curve(s: float) -> Tuple[float, float, float, float]:
        a = math.radians(angle) * s
        # Łuk styczny do kierunku startowego (nos = oś X). Przy skręcie w lewo
        # (sign=+1) łuk wygina się w +Y, przy skręcie w prawo w -Y; początkowa
        # prędkość w obu przypadkach jest skierowana w +X.
        x = r * math.sin(abs(a))
        y = sign * r * (1 - math.cos(abs(a)))
        return (x, y, 0.0, math.degrees(a))

    builder.curve(curve, _arc_len(r, angle), speed)
    traj = builder.finish(label, meta={"radius": r, "angle": angle})
    _check_limits(traj, limits)
    return traj


def plan_arc(angle_deg: float, radius_cm: float, *, limits: PlanLimits,
             profile: CalibrationProfile, speed: float, label: str = "arc") -> Trajectory:
    """Łuk o zadanym kącie (dodatni = w lewo) - ``plan_turn`` bez wyboru strony."""
    return plan_turn(angle_deg, radius_cm,
                     side=1 if angle_deg >= 0 else -1,
                     limits=limits, profile=profile, speed=speed, label=label)


def plan_circle(radius_cm: float, *, direction: str = "right", face: str = "tangent",
                limits: PlanLimits, profile: CalibrationProfile, speed: float,
                label: str = "circle") -> Trajectory:
    """Pełne okrążenie o promieniu ``radius_cm``.

    :param direction: ``right`` (zgodnie z ruchem wskazówek) lub ``left``
    :param face: ``tangent`` (nos wzdłuż toru), ``center`` (nos w środek),
        ``fixed`` (nos bez zmian)
    """
    if direction not in ("right", "left"):
        raise PathError("direction musi być 'right' albo 'left'")
    if face not in ("tangent", "center", "fixed"):
        raise PathError("face musi być 'tangent', 'center' albo 'fixed'")
    sign = 1 if direction == "left" else -1
    text = label or f"circle r={radius_cm:.0f} {direction}"
    return plan_turn(360.0, radius_cm, side=sign, limits=limits, profile=profile,
                     speed=speed, label=text)


# ------------------------------------------------------------------ walidacja
def _check_limits(traj: Trajectory, limits: PlanLimits, start=(0.0, 0.0, 0.0),
                  check_height: bool = False) -> None:
    """Sprawdź, czy trajektoria mieści się w limitach (promień, opcjonalnie wysokość)."""
    tolerance = 1e-6
    for sample in traj.samples:
        gx = start[0] + sample.x
        gy = start[1] + sample.y
        if math.hypot(gx, gy) > limits.max_radius_from_start_cm + tolerance:
            raise PathError(
                f"Manewr oddala się o {math.hypot(gx, gy):.0f} cm od startu, "
                f"limit to {limits.max_radius_from_start_cm:.0f} cm."
            )
        if check_height:
            gz = start[2] + sample.z
            if gz > limits.max_height_cm:
                raise PathError(
                    f"Wysokość {gz:.0f} cm przekracza limit {limits.max_height_cm:.0f} cm."
                )


# --------------------------------------------- manewry: orbit, slalom, osemka
def plan_orbit(radius_cm: float, turns: float = 1.0, *, direction: str = "right",
               limits: PlanLimits, profile: CalibrationProfile, speed: float,
               label: Optional[str] = None) -> Trajectory:
    """Krążenie wokół punktu z nosem zawsze do środka.

    Tor to okrąg o promieniu ``radius_cm``; pozycja startowa leży na okręgu,
    a yaw obraca się o ``turns * 360 stopni`` (nos patrzy w środek).
    """
    if turns <= 0:
        raise PathError("turns musi być > 0")
    if radius_cm < limits.min_radius_cm:
        raise PathError(
            f"Promień {radius_cm:.0f} cm jest za mały (min. {limits.min_radius_cm:.0f} cm).")
    if direction not in ("right", "left"):
        raise PathError("direction musi być 'right' albo 'left'")
    sign = 1 if direction == "left" else -1
    limit = min(limits.max_yaw_rate_dps, profile.max_yaw_rate_dps)
    required_yaw_rate = math.degrees(speed / radius_cm)
    if required_yaw_rate > limit:
        needed = speed / math.radians(limit)
        raise PathError(
            f"Orbit r={radius_cm:.0f} cm przy v={speed:.0f} cm/s wymaga obrotu "
            f"{required_yaw_rate:.0f} stopni/s (limit {limit:.0f} stopni/s). "
            f"Zwiększ promień do min. {needed:.0f} cm lub zmniejsz prędkość."
        )
    r = radius_cm
    total_angle = 360.0 * turns
    builder = TrajectoryBuilder(limits, profile)
    cx, cy = 0.0, sign * r  # środek okręgu po stronie skrętu
    # Kurs wyjściowy to „nos w środek okręgu” (dla right: -90°, dla left: +90°).
    # Dron startuje z kursem 0, więc najpierw obraca się w miejscu - inaczej
    # pierwsza próbka planu zmieniałaby yaw skokiem, a dron poleciałby w złą stronę.
    start_yaw = math.degrees(math.atan2(cy - 0.0, cx - 0.0))
    builder.rotate(((start_yaw + 180.0) % 360.0) - 180.0)

    def curve(s: float) -> Tuple[float, float, float, float]:
        theta = math.radians(total_angle) * s
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        px = cx + (0.0 - cx) * cos_t - sign * (0.0 - cy) * sin_t
        py = cy + sign * (0.0 - cx) * sin_t + (0.0 - cy) * cos_t
        yaw = math.degrees(math.atan2(cy - py, cx - px))  # nos w środek okręgu
        return (px, py, 0.0, yaw)

    text = label or f"orbit r={r:.0f} turns={turns:g}"
    builder.curve(curve, _arc_len(r, total_angle), speed)
    traj = builder.finish(text, meta={"radius": r, "direction": direction, "turns": turns})
    _check_limits(traj, limits, start=(0.0, 0.0, 0.0))
    return traj


def plan_slalom(gates: int = 4, spacing_cm: float = 100.0, width_cm: float = 60.0,
                *, limits: PlanLimits, profile: CalibrationProfile, speed: float,
                label: Optional[str] = None) -> Trajectory:
    """Slalom między bramkami ustawionymi w linii co ``spacing_cm``.

    Środek pierwszej bramki leży w ``(spacing/2, 0)``, kolejne wzdłuż osi X.
    Dron przelatuje na zmianę o ``width_cm`` w lewo/prawo, przechodząc przez
    środek każdej bramki. ``meta["gates"]`` zawiera środki bramek (podgląd UI).
    """
    if gates < 1:
        raise PathError("gates musi być >= 1")
    if spacing_cm <= 0 or width_cm <= 0:
        raise PathError("spacing i width muszą być dodatnie")
    half = width_cm / 2.0
    gate_points = [(spacing_cm / 2 + i * spacing_cm, 0.0, 0.0) for i in range(gates)]
    waypoints = [(0.0, 0.0, 0.0)]
    for index, (gx, gy, gz) in enumerate(gate_points):
        before = 1.0 if (index - 1) % 2 == 0 else -1.0
        after = 1.0 if index % 2 == 0 else -1.0
        offset_before = 0.0 if index == 0 else -before * half
        offset_after = -after * half if index < gates - 1 else 0.0
        waypoints.append((gx - spacing_cm * 0.25, gy + offset_before, gz))
        waypoints.append((gx, gy, gz))  # dokładnie środek bramki
        waypoints.append((gx + spacing_cm * 0.25, gy + offset_after, gz))
    waypoints.append((spacing_cm / 2 + (gates - 1) * spacing_cm + spacing_cm, 0.0, 0.0))

    planar = [(x, y) for x, y, _ in waypoints]
    sampled = _resample_by_arclength(_natural_spline_2d(planar, samples_per_segment=36), 800)
    length = sum(math.dist(a, b) for a, b in zip(sampled, sampled[1:]))
    builder = TrajectoryBuilder(limits, profile)

    def curve(s: float) -> Tuple[float, float, float, float]:
        # ciągła interpolacja po długości krzywej (bez skoków na indeksach próbek)
        pos = s * (len(sampled) - 1)
        i0 = min(int(pos), len(sampled) - 2)
        frac = pos - i0
        a, b = sampled[i0], sampled[i0 + 1]
        x = a[0] + (b[0] - a[0]) * frac
        y = a[1] + (b[1] - a[1]) * frac
        j0 = min(i0 + 1, len(sampled) - 2)
        c = sampled[j0 + 1]
        yaw = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]))
        return (x, y, 0.0, yaw)

    text = label or f"slalom {gates} bramek"
    builder.curve(curve, length, speed, smooth_yaw=True, yaw_window=13)
    traj = builder.finish(text, meta={"gates": gate_points, "width": width_cm})
    _check_limits(traj, limits)
    return traj


def plan_figure_eight(radius_cm: float = 80.0, *, limits: PlanLimits,
                      profile: CalibrationProfile, speed: float,
                      label: Optional[str] = None) -> Trajectory:
    """Ósemka: dwa okręgi o środku (0, ±r) styczne w punkcie (0, 0)."""
    if radius_cm < limits.min_radius_cm:
        raise PathError(
            f"Promien {radius_cm:.0f} cm jest za maly (min. {limits.min_radius_cm:.0f} cm).")
    limit = min(limits.max_yaw_rate_dps, profile.max_yaw_rate_dps)
    required_yaw_rate = math.degrees(speed / radius_cm)
    if required_yaw_rate > limit:
        raise PathError(
            f"Osemka r={radius_cm:.0f} cm przy v={speed:.0f} cm/s wymaga "
            f"{required_yaw_rate:.0f} stopni/s (limit {limit:.0f} stopni/s). "
            f"Zwieksz promien do min. {speed / math.radians(limit):.0f} cm "
            "lub zmniejsz predkosc.")
    r = radius_cm
    # długość: dwa pełne okręgi (2 x 2*pi*r)
    length = 4.0 * math.pi * r

    def curve(s: float) -> Tuple[float, float, float, float]:
        eps = 1e-4

        def point(u: float) -> Tuple[float, float]:
            # Okrag A (gora): srodek (0, r), start (0,0) = kat -90, obieg do 270.
            # Okrag B (dol):  srodek (0,-r), start (0,0) = kat 90, obieg do -270.
            if u <= 0.5:
                phi = math.radians(-90.0 + 360.0 * (u / 0.5))
                return (r * math.cos(phi), r + r * math.sin(phi))
            phi = math.radians(90.0 - 360.0 * ((u - 0.5) / 0.5))
            return (r * math.cos(phi), -r + r * math.sin(phi))

        px, py = point(s)
        ahead = point(min(s + eps, 1.0))
        behind = point(max(s - eps, 0.0))
        yaw = math.degrees(math.atan2(ahead[1] - behind[1], ahead[0] - behind[0]))
        return (px, py, 0.0, yaw % 360.0)

    text = label or f"figure_eight r={r:.0f}"
    builder = TrajectoryBuilder(limits, profile)
    builder.curve(curve, length, speed, smooth_yaw=True, yaw_window=21)
    traj = builder.finish(text, meta={"radius": r})
    _check_limits(traj, limits)
    return traj


def plan_spiral(radius_cm: float = 100.0, height_cm: float = 100.0, turns: float = 2.0,
                *, limits: PlanLimits, profile: CalibrationProfile, speed: float,
                label: Optional[str] = None) -> Trajectory:
    """Spirala wznoszaca: okragly tor o stalym promieniu, wysokosc rosnie o ``height_cm``."""
    if turns <= 0 or height_cm <= 0:
        raise PathError("turns i height musza byc > 0")
    if radius_cm < limits.min_radius_cm:
        raise PathError(
            f"Promien {radius_cm:.0f} cm jest za maly (min. {limits.min_radius_cm:.0f} cm).")
    limit = min(limits.max_yaw_rate_dps, profile.max_yaw_rate_dps)
    required_yaw_rate = math.degrees(speed / radius_cm)
    if required_yaw_rate > limit:
        raise PathError(
            f"Spirala r={radius_cm:.0f} cm przy v={speed:.0f} cm/s wymaga "
            f"{required_yaw_rate:.0f} stopni/s (limit {limit:.0f} stopni/s). "
            "Zwieksz promien lub zmniejsz predkosc.")
    r = radius_cm
    total_angle = 360.0 * turns

    def curve(s: float) -> Tuple[float, float, float, float]:
        theta = math.radians(total_angle) * s
        x = r * math.sin(theta)
        y = r * (1 - math.cos(theta))
        z = height_cm * s
        yaw = math.degrees(theta)
        return (x, y, z, yaw)

    text = label or f"spiral r={r:.0f} h={height_cm:.0f}"
    builder = TrajectoryBuilder(limits, profile)
    path_len = _arc_len(r, total_angle) * 1.05 + height_cm
    builder.curve(curve, path_len, speed)
    traj = builder.finish(text, meta={"radius": r, "height": height_cm})
    _check_limits(traj, limits, check_height=True)
    return traj


def plan_path(points: Sequence[Point], *, limits: PlanLimits,
              profile: CalibrationProfile, speed: float, smooth: bool = True,
              label: Optional[str] = None) -> Trajectory:
    """Przelot przez liste punktow (wzglednych, w ukladzie startu manewru).

    ``smooth=True``: gladka krzywa (spline Catmulla-Roma) przez punkty;
    ``smooth=False``: lamana z rozpedzaniem/hamowaniem na kazdym odcinku.
    """
    if len(points) < 2:
        raise PathError("path wymaga co najmniej 2 punktow")
    pts = [(float(x), float(y), float(z)) for x, y, z in points]
    if smooth:
        planar = _resample_by_arclength(
            _natural_spline_2d([(x, y) for x, y, _ in pts], samples_per_segment=20), 800)
        n = len(pts) - 1
        heights = []
        for i in range(len(planar)):
            pos = i / (len(planar) - 1) * n
            seg = min(int(pos), n - 1)
            frac = pos - seg
            heights.append(pts[seg][2] + (pts[seg + 1][2] - pts[seg][2]) * frac)
        sampled = [(planar[i][0], planar[i][1], heights[i]) for i in range(len(planar))]
    else:
        sampled = list(pts)
    length = sum(math.dist(a, b) for a, b in zip(sampled, sampled[1:]))
    builder = TrajectoryBuilder(limits, profile)
    total = len(sampled) - 1

    def curve(s: float) -> Tuple[float, float, float, float]:
        idx = s * total
        i0 = min(int(idx), total - 1)
        frac = idx - i0
        a, b = sampled[i0], sampled[i0 + 1]
        x = a[0] + (b[0] - a[0]) * frac
        y = a[1] + (b[1] - a[1]) * frac
        z = a[2] + (b[2] - a[2]) * frac
        yaw = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        return (x, y, z, yaw)

    text = label or f"path {len(points)} pkt"
    builder.curve(curve, max(length, 1.0), speed, smooth_yaw=True, yaw_window=11)
    traj = builder.finish(text, meta={"points": pts, "smooth": smooth})
    _check_limits(traj, limits, check_height=True)
    return traj


def _resample_by_arclength(points: Sequence[Tuple[float, float]],
                           count: int = 800) -> List[Tuple[float, float]]:
    """Probkuj krzywa rownomiernie po dlugosci luku (rowna predkosc, brak skokow)."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1]
    if total <= 0:
        return [pts[0]] * count
    result: List[Tuple[float, float]] = []
    j = 0
    for i in range(count):
        target = total * i / (count - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        seg = cum[j + 1] - cum[j]
        frac = 0.0 if seg <= 0 else (target - cum[j]) / seg
        a, b = pts[j], pts[j + 1]
        result.append((a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac))
    return result


def _natural_spline_2d(points: Sequence[Tuple[float, float]],
                       samples_per_segment: int = 20) -> List[Tuple[float, float]]:
    """Gladka krzywa 2D przez punkty (spline Catmulla-Roma), z punktem koncowym."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    extended = [pts[0]] + pts + [pts[-1]]
    result: List[Tuple[float, float]] = []
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        for k in range(samples_per_segment):
            t = k / samples_per_segment
            t2, t3 = t * t, t * t * t
            x = 0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            result.append((x, y))
    result.append(pts[-1])
    return result


def _trapezoid_params(length: float, speed: float,
                      accel: float) -> Tuple[float, float, float, float, float]:
    """Parametry profilu trapezowego: ``(t_acc, t_cruise, t_dec, v_peak, a)``."""
    if length <= 0:
        return (0.0, 0.0, 0.0, 0.0, accel)
    if speed * speed / accel >= length:  # profil trójkątny (bez fazy stałej prędkości)
        # droga = a * t_acc^2 -> t_acc = sqrt(length / a), v_peak = a * t_acc
        t = math.sqrt(length / accel)
        return (t, 0.0, t, accel * t, accel)
    t_acc = speed / accel
    d_acc = 0.5 * accel * t_acc * t_acc
    t_cruise = (length - 2 * d_acc) / speed
    return (t_acc, t_cruise, t_acc, speed, accel)


def _trapezoid_distance(t: float, t_acc: float, t_cruise: float, t_dec: float,
                        v_peak: float, accel: float) -> float:
    """Przebyta droga w chwili ``t`` dla profilu trapezowego."""
    if t <= 0:
        return 0.0
    if t < t_acc:
        return 0.5 * accel * t * t
    d_acc = 0.5 * accel * t_acc * t_acc
    if t < t_acc + t_cruise:
        return d_acc + v_peak * (t - t_acc)
    total = 2 * d_acc + v_peak * t_cruise
    rem = (t_acc + t_cruise + t_dec) - t
    if rem <= 0:
        return total
    return total - 0.5 * accel * rem * rem
