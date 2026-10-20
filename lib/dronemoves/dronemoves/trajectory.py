"""Trajektorie jako funkcje czasu: pozycja, yaw, prędkości i wychylenia RC.

Wszystkie wielkości są w układzie drona: X do przodu, Y w lewo, Z w górę (cm),
yaw w stopniach (dodatni = w lewo/CCW). Trajektoria to lista próbek w stałym
kroku czasu (domyślnie 50 ms = 20 Hz), a każda próbka zna prędkości i gotowe
wychylenia RC (``-100..100``) wyliczone z profilu kalibracji.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

from .calibration import CalibrationProfile

__all__ = ["Sample", "Trajectory", "trapezoid_profile", "smoothstep"]

Vec3 = Tuple[float, float, float]


def smoothstep(x: float) -> float:
    """Gładka funkcja 0..1 (zerowa prędkość na obu końcach)."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def trapezoid_profile(distance: float, speed: float, accel: float,
                      duration: float | None = None) -> Tuple[float, float, float, float, float]:
    """Profil trapezowy (rozpędzanie - jazda - hamowanie).

    :param distance: długość drogi (cm)
    :param speed: prędkość maksymalna (cm/s)
    :param accel: przyspieszenie (cm/s²)
    :param duration: wymuszony czas trwania (s); gdy podany, prędkość maksymalna
        jest dopasowana tak, aby zmieścić się w czasie
    :return: ``(t_acc, t_cruise, t_dec, v_peak, a)``
    """
    if distance <= 0:
        return (0.0, 0.0, 0.0, 0.0, accel)
    if speed <= 0 or accel <= 0:
        raise ValueError("speed i accel muszą być dodatnie")
    if duration is not None and duration > 0:
        # prędkość szczytowa przy symetrycznym profilu: d = v*(T - v/a)
        disc = max(0.0, duration * duration - 4.0 * distance / accel)
        v_peak = min(speed, 0.5 * accel * (duration - math.sqrt(disc)))
    else:
        v_peak = speed
    t_acc = v_peak / accel
    d_acc = 0.5 * accel * t_acc * t_acc
    if 2 * d_acc >= distance:
        # profil trójkątny - prędkość szczytowa mniejsza niż zadana
        v_peak = math.sqrt(accel * distance)
        t_acc = v_peak / accel
        return (t_acc, 0.0, t_acc, v_peak, accel)
    t_cruise = (distance - 2 * d_acc) / v_peak
    return (t_acc, t_cruise, t_acc, v_peak, accel)


@dataclass
class Sample:
    """Pojedyncza próbka trajektorii (stan w chwili ``t``)."""

    t: float
    x: float
    y: float
    z: float
    yaw: float
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    yaw_rate: float = 0.0
    rc: Tuple[int, int, int, int] = (0, 0, 0, 0)

    def position(self) -> Vec3:
        return (self.x, self.y, self.z)


@dataclass
class Trajectory:
    """Zaplanowana trajektoria manewru (lista próbek + metadane)."""

    samples: List[Sample] = field(default_factory=list)
    label: str = ""
    mode: str = "rc"
    #: dodatkowe dane z planera (np. punkty bramek w slalomie)
    meta: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ info
    @property
    def duration(self) -> float:
        return self.samples[-1].t if self.samples else 0.0

    def points(self) -> List[Vec3]:
        """Lista punktów (x, y, z) - do podglądu/rysowania."""
        return [s.position() for s in self.samples]

    def at(self, t: float) -> Sample:
        """Próbka najbliższa chwili ``t`` (interpolacja liniowa)."""
        if not self.samples:
            raise ValueError("Pusta trajektoria")
        if t <= self.samples[0].t:
            return self.samples[0]
        if t >= self.samples[-1].t:
            return self.samples[-1]
        for index in range(1, len(self.samples)):
            if self.samples[index].t >= t:
                a, b = self.samples[index - 1], self.samples[index]
                span = b.t - a.t
                frac = 0.0 if span <= 0 else (t - a.t) / span
                lerp = lambda k: getattr(a, k) + (getattr(b, k) - getattr(a, k)) * frac  # noqa: E731
                dyaw = ((b.yaw - a.yaw + 540) % 360) - 180
                return Sample(
                    t=t, x=lerp("x"), y=lerp("y"), z=lerp("z"),
                    yaw=a.yaw + dyaw * frac,
                    vx=lerp("vx"), vy=lerp("vy"), vz=lerp("vz"),
                    yaw_rate=lerp("yaw_rate"), rc=b.rc,
                )
        return self.samples[-1]

    # ------------------------------------------------------- narzędzia planera
    def max_speed(self) -> float:
        best = 0.0
        for s in self.samples:
            best = max(best, math.hypot(s.vx, s.vy), abs(s.vz))
        return best

    def max_accel(self) -> float:
        """Maksymalna zmiana prędkości liniowej między próbkami [cm/s²]."""
        worst = 0.0
        for a, b in zip(self.samples, self.samples[1:]):
            dt = b.t - a.t
            if dt <= 0:
                continue
            dv = math.hypot(b.vx - a.vx, b.vy - a.vy, b.vz - a.vz)
            worst = max(worst, dv / dt)
        return worst

    def max_yaw_accel(self) -> float:
        """Maksymalna zmiana prędkości obrotu między próbkami [°/s²]."""
        worst = 0.0
        for a, b in zip(self.samples, self.samples[1:]):
            dt = b.t - a.t
            if dt > 0:
                worst = max(worst, abs(b.yaw_rate - a.yaw_rate) / dt)
        return worst

    def with_rc(self, profile: CalibrationProfile) -> "Trajectory":
        """Uzupełnij wychylenia RC na podstawie profilu kalibracji (mapa prędkości)."""
        for s in self.samples:
            s.rc = (
                profile.speed_to_rc(s.vx),           # fb (przód+)
                profile.speed_to_rc(-s.vy),          # lr (lewo+ -> w djitellopy lr+ = lewo)
                profile.speed_to_rc(s.vz),           # ud
                profile.yaw_rate_to_rc(s.yaw_rate),  # yaw (+ = w lewo)
            )
        return self

    def smooth_yaw(self, window: int = 9) -> "Trajectory":
        """Wygładź kąt nosa w czasie (ruchoma średnia) - bez szarpnięć na łączeniach.

        Uśredniamy ``yaw`` na oknie ``window`` próbek (dla 20 Hz i 9 próbek to
        0.45 s), a następnie przeliczamy ``yaw_rate`` z wygładzonego przebiegu.
        """
        n = len(self.samples)
        if n < 3 or window < 3:
            return self
        half = window // 2
        raw = [s.yaw for s in self.samples]
        smoothed = []
        for i in range(n):
            acc = [0.0, 0.0]  # suma wektorów jednostkowych (obsługa przejścia 360->0)
            for j in range(max(0, i - half), min(n, i + half + 1)):
                rad = math.radians(raw[j])
                acc[0] += math.cos(rad)
                acc[1] += math.sin(rad)
            smoothed.append(math.degrees(math.atan2(acc[1], acc[0])) % 360.0)
        for i, sample in enumerate(self.samples):
            sample.yaw = smoothed[i]
            if i > 0:
                prev = self.samples[i - 1]
                dt = sample.t - prev.t
                if dt > 0:
                    dyaw = ((sample.yaw - prev.yaw + 540) % 360) - 180
                    sample.yaw_rate = dyaw / dt
            else:
                sample.yaw_rate = 0.0
        return self
