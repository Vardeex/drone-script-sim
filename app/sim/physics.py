"""Prosty model ruchu drona (kinematyka liniowa).

Układ współrzędnych (zgodnie z wymaganiami projektu):
    X - do przodu, Y - w lewo, Z - w górę (prawoskrętny), yaw w stopniach.
    yaw = 0 oznacza przód skierowany w +X, yaw dodatni = obrót w lewo (CCW),
    tak jak w Tello (rotate_counter_clockwise zwiększa yaw).

Ruch jest modelowany jako przesunięcie po prostej (dla ``curve``: łuk
opisany punktem kontrolnym krzywej Beziera 2. stopnia) w czasie wynikającym
z prędkości. Opcjonalnie uwzględniamy rampę przyspieszenia/hamowania.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]

#: Maksymalne przyspieszenie modelu [cm/s^2] używane, gdy accel=True.
DEFAULT_ACCEL = 100.0


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def rotate_vector(x: float, y: float, yaw_deg: float) -> Tuple[float, float]:
    """Obróć wektor z układu drona (przód/lewo) do układu globalnego.

    yaw=0 -> bez zmian; yaw=90 -> przód drona wskazuje +Y (lewo).
    """
    rad = math.radians(yaw_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    gx = x * cos_a - y * sin_a
    gy = x * sin_a + y * cos_a
    return gx, gy


def bezier_point(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], t: float) -> Vec3:
    """Punkt na krzywej Beziera 2. stopnia (parametr t w [0,1])."""
    u = 1.0 - t
    return tuple(u * u * a + 2 * u * t * b + t * t * c for a, b, c in zip(p0, p1, p2))  # type: ignore[return-value]


def bezier_tangent(p0: Sequence[float], p1: Sequence[float], p2: Sequence[float], t: float) -> Vec3:
    """Pochodna krzywej Beziera 2. stopnia względem t."""
    return tuple(2.0 * (1.0 - t) * (b - a) + 2.0 * t * (c - b) for a, b, c in zip(p0, p1, p2))  # type: ignore[return-value]


def path_length(points: Iterable[Sequence[float]]) -> float:
    """Długość łamanej 3D w cm."""
    pts = list(points)
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.dist(a, b)
    return total


@dataclass
class LinearMove:
    """Przejście (segment) ruchu o zadanej prędkości i opcjonalnej rampie."""

    start: Vec3
    end: Vec3
    speed: float = 50.0  # cm/s
    accel: bool = False
    accel_value: float = DEFAULT_ACCEL  # cm/s^2
    #: Punkty pośrednie (dla ``curve``) - próbkowane z krzywej Beziera.
    polyline: List[Vec3] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.polyline:
            self.polyline = [tuple(self.start), tuple(self.end)]  # type: ignore[list-item]
        self._cum = [0.0]
        for a, b in zip(self.polyline, self.polyline[1:]):
            self._cum.append(self._cum[-1] + math.dist(a, b))
        self.length = self._cum[-1]

    # ------------------------------------------------------------------ czas
    def _phase_time(self, distance: float) -> float:
        """Czas rozpędzania do prędkości szczytowej przy dostępnej odległości."""
        if distance <= 0.0:
            return 0.0
        v = min(self.speed, math.sqrt(self.accel_value * distance))
        return v / self.accel_value

    def duration(self) -> float:
        if self.length <= 0.0:
            return 0.0
        if not self.accel:
            return self.length / self.speed if self.speed > 0 else 0.0
        t_ramp = self._phase_time(self.length)
        d_ramp = 0.5 * self.accel_value * t_ramp * t_ramp
        if 2 * d_ramp >= self.length:
            # trójkątny profil prędkości
            v_peak = math.sqrt(self.accel_value * self.length)
            return 2.0 * v_peak / self.accel_value
        d_cruise = self.length - 2 * d_ramp
        v_cruise = self.accel_value * t_ramp
        return 2 * t_ramp + d_cruise / v_cruise

    # -------------------------------------------------------------- prędkość
    def speed_at(self, elapsed: float) -> float:
        """Prędkość skalarna w chwili ``elapsed`` (0..duration) w cm/s."""
        total = self.duration()
        if total <= 0.0:
            return 0.0
        t = _clamp(elapsed, 0.0, total)
        if not self.accel:
            return self.speed
        t_ramp = self._phase_time(self.length)
        d_ramp = 0.5 * self.accel_value * t_ramp * t_ramp
        if 2 * d_ramp >= self.length:
            v_peak = math.sqrt(self.accel_value * self.length)
            t_peak = v_peak / self.accel_value
            if t <= t_peak:
                return self.accel_value * t
            return self.accel_value * max(0.0, total - t)
        v_cruise = self.accel_value * t_ramp
        if t <= t_ramp:
            return self.accel_value * t
        if t <= total - t_ramp:
            return v_cruise
        return self.accel_value * max(0.0, total - t)

    def distance_at(self, elapsed: float) -> float:
        """Przebyta odległość po łamanej w danej chwili."""
        total = self.duration()
        if total <= 0.0:
            return 0.0
        t = _clamp(elapsed, 0.0, total)
        if not self.accel:
            return _clamp(self.speed * t, 0.0, self.length)
        t_ramp = self._phase_time(self.length)
        d_ramp = 0.5 * self.accel_value * t_ramp * t_ramp
        if 2 * d_ramp >= self.length:
            v_peak = math.sqrt(self.accel_value * self.length)
            t_peak = v_peak / self.accel_value
            if t <= t_peak:
                return 0.5 * self.accel_value * t * t
            remain = total - t
            return self.length - 0.5 * self.accel_value * remain * remain
        v_cruise = self.accel_value * t_ramp
        if t <= t_ramp:
            return 0.5 * self.accel_value * t * t
        if t <= total - t_ramp:
            return d_ramp + v_cruise * (t - t_ramp)
        remain = total - t
        return self.length - 0.5 * self.accel_value * remain * remain

    # --------------------------------------------------------------- pozycja
    def position_at(self, elapsed: float) -> Vec3:
        """Pozycja na trasie w danej chwili (współrzędne globalne)."""
        if self.length <= 0.0:
            return tuple(self.end)  # type: ignore[return-value]
        d = self.distance_at(elapsed)
        for i in range(1, len(self._cum)):
            if d <= self._cum[i] or i == len(self._cum) - 1:
                seg = self._cum[i] - self._cum[i - 1]
                frac = 0.0 if seg <= 0 else (d - self._cum[i - 1]) / seg
                a = self.polyline[i - 1]
                b = self.polyline[i]
                return tuple(a[k] + (b[k] - a[k]) * frac for k in range(3))  # type: ignore[return-value]
        return tuple(self.end)  # type: ignore[return-value]

    def velocity_at(self, elapsed: float) -> Vec3:
        """Wektor prędkości 3D [cm/s] w danej chwili."""
        speed = self.speed_at(elapsed)
        if speed <= 0.0 or self.length <= 0.0:
            return (0.0, 0.0, 0.0)
        d = self.distance_at(elapsed)
        idx = len(self._cum) - 1
        for i in range(1, len(self._cum)):
            if d <= self._cum[i]:
                idx = i
                break
        a = self.polyline[idx - 1]
        b = self.polyline[idx]
        seg = math.dist(a, b)
        if seg <= 0.0:
            return (0.0, 0.0, 0.0)
        return tuple(speed * (b[k] - a[k]) / seg for k in range(3))  # type: ignore[return-value]


def relative_move_points(
    position: Vec3,
    yaw: float,
    dx: float,
    dy: float,
    dz: float,
    curve_control: Tuple[float, float, float] | None = None,
    curve_samples: int = 24,
) -> List[Vec3]:
    """Punkty łamanej dla ruchu względnego (w układzie drona) w układzie globalnym.

    ``dx`` przód, ``dy`` lewo, ``dz`` góra - w cm, zgodnie z API Tello.
    Dla ``curve`` ``curve_control`` to punkt kontrolny również w układzie drona.
    """
    sx, sy, sz = position
    gx, gy = rotate_vector(dx, dy, yaw)
    end = (sx + gx, sy + gy, sz + dz)
    if curve_control is None:
        return [(sx, sy, sz), end]
    cgx, cgy = rotate_vector(curve_control[0], curve_control[1], yaw)
    p1 = (sx + cgx, sy + cgy, sz + curve_control[2])
    p0 = (sx, sy, sz)
    return [bezier_point(p0, p1, end, i / curve_samples) for i in range(curve_samples + 1)]
