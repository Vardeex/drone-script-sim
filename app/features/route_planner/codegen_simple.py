"""Generator trybu „prosta” - czyste ``djitellopy`` (bez dronemoves).

Każdy odcinek to ``go_xyz_speed`` w układzie **aktualnego kursu drona**
(``x`` = przód, ``y`` = lewo, ``z`` = góra), więc przed ruchem dron obraca się
tak, by oś ``x`` wskazywała kierunek odcinka - sekwencja ``rotate_*`` + ``go``.
Obroty wynikają z geometrii: ``yaw = atan2(-dy, dx)`` (konwencja Tello,
dodatni = w prawo).

Zasady Tello:

* jeden ruch 20-500 cm: dłuższe odcinki dzielimy na równe części (każda
  <= 500 cm), krótsze (< 20 cm) łączymy z sąsiednim, a gdy nie da się - zgłaszamy
  problem (nie generujemy kodu),
* ``rotate_*`` przyjmuje 1-360°, więc obrót 180° itp. jest wprost,
* zawis = ``time.sleep``, kurs w punkcie = dodatkowy ``rotate_*``.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .codegen_common import battery_check, num
from .model import (
    MAX_MOVE_CM, MIN_MOVE_CM, MIN_SPEED_CMS, MAX_SPEED_CMS,
    Route, RouteError, route_block,
)


def normalize_yaw(angle: float) -> float:
    """Kąt w zakresie 0-360 (konwencja Tello)."""
    return angle % 360.0


def body_move(dx: float, dy: float, heading: float) -> Tuple[float, float]:
    """Przemieszczenie ``(dx, dy)`` w układzie projektu -> układ ``go_xyz_speed``.

    :param heading: kurs nosa drona w konwencji API (Tello: dodatni = w prawo)

    Układ projektu: ``x`` = przód, ``y`` = lewo, ``z`` = góra. Kurs ``h``
    (dodatni = w prawo, zgodnie z zegarem) daje w tym układzie:

    * oś nosa (przód drona) ``(cos h, -sin h)``,
    * oś lewej ręki ``(sin h, cos h)``.

    ``go_xyz_speed`` przyjmuje ``x`` = przód, ``y`` = lewo **względem nosa**,
    czyli rzut przemieszczenia na te osie::

        along = dx*cos h - dy*sin h
        left  = dx*sin h + dy*cos h

    Sprawdzenie (kurs 90°, nos w prawo na -Y): ruch ``(dx, dy) = (100, 0)``
    daje ``go_xyz_speed(0, 100, ...)`` - zgodnie z zachowaniem symulatora
    (``rotate_clockwise(90)`` + ``go_xyz_speed(0, 100, 0)`` → ``(100, 0)``).
    """
    rad = math.radians(heading)
    cos_h, sin_h = math.cos(rad), math.sin(rad)
    along = dx * cos_h - dy * sin_h
    left = dx * sin_h + dy * cos_h
    return along, left


def turn_delta(yaw: float, target: float) -> float:
    """Najkrótszy obrót z ``yaw`` do ``target`` (-180..180, + = w prawo).

    ``yaw`` i ``target`` są w konwencji ``get_yaw()`` (dodatni = w prawo, ale
    ``rotate_counter_clockwise`` zwraca wartość ujemną - patrz
    :func:`apply_turn`). Różnica jest liczona na okręgu, więc działa dla
    obu znaków.
    """
    return (target - yaw + 180.0) % 360.0 - 180.0


def apply_turn(yaw: float, delta: float) -> float:
    """Nowy kurs po obrocie o ``delta`` (+ = ``rotate_clockwise``).

    ``djitellopy.get_yaw()`` po ``rotate_counter_clockwise(90)`` zwraca
    ``-90``, więc obrót w lewo wykonuje się jako ``rotate_counter_clockwise``
    o ``|delta|``, a kurs wewnętrzny liczymy w zakresie ``-180..180`` -
    tak, jak podaje go API.
    """
    value = (yaw + delta + 180.0) % 360.0 - 180.0
    return value


def turn_command(yaw: float, target: float) -> Tuple[float, float]:
    """Dobierz ``(kąt, kierunek)``: ``+1`` = ``rotate_clockwise``, ``-1`` = ``ccw``."""
    delta = turn_delta(yaw, target)
    return abs(delta), (1.0 if delta >= 0 else -1.0)


def yaw_from_track(dx: float, dy: float) -> float:
    """Kurs nosa po torze odcinka (konwencja API: + = w prawo)."""
    return math.degrees(math.atan2(-dy, dx)) % 360.0


# ------------------------------------------------------------------- segmentacja
def plan_segments(route: Route) -> List[Tuple[Tuple[float, float, float], int]]:
    """Segmenty ruchu: ``(przemieszczenie (dx, dy, dz), punkt docelowy)``.

    Zasady Tello (20-500 cm na jeden ``go_xyz_speed``):

    * odcinek <= 500 cm: jeden ruch,
    * dłuższy: dzielony na równe części w :func:`generate` (każda <= 500 cm),
    * krótszy niż 20 cm (w tym 0): dołączany do poprzedniego segmentu,
    * pierwszy odcinek krótszy niż 20 cm jest łączony z następnym.

    Segmenty zwracane przez tę funkcję kończą się zawsze w punkcie trasy, więc
    ``go_xyz_speed`` prowadzi drona dokładnie przez plan (pierwszy wyjątek:
    punkt bliżej niż 20 cm od startu jest mijany w ruchu do punktu 2).
    """
    points = [(0.0, 0.0, 80.0)] + route.waypoints()
    segments: List[Tuple[Tuple[float, float, float], int]] = []
    for index in range(1, len(points)):
        start, end = points[index - 1], points[index]
        dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        if distance < MIN_MOVE_CM - 1e-9 and segments:
            # za krótki odcinek: wydłuż poprzedni segment do tego punktu
            origin = (points[segments[-1][1] - 2])
            segments[-1] = ((end[0] - origin[0], end[1] - origin[1],
                             end[2] - origin[2]), index + 1)
            continue
        segments.append(((dx, dy, dz), index + 1))
    return segments


def split_segment(dx: float, dy: float, dz: float) -> List[Tuple[float, float, float]]:
    """Podziel ruch na części <= 500 cm (równe, ostatnia reszta)."""
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if distance <= MAX_MOVE_CM:
        return [(dx, dy, dz)]
    parts = int(math.ceil(distance / MAX_MOVE_CM))
    step = (dx / parts, dy / parts, dz / parts)
    result = [step for _ in range(parts - 1)]
    result.append((dx - step[0] * (parts - 1), dy - step[1] * (parts - 1),
                   dz - step[2] * (parts - 1)))
    return result


def heading_target(route: Route, index: int) -> Optional[float]:
    """Kurs nosa wymagany po dojeździe do punktu ``index`` (konwencja API: + = prawo)."""
    point = route.points[index]
    if point.heading == "fixed":
        return point.yaw_deg % 360.0
    if point.heading == "point" and point.look_at is not None:
        lx, ly = point.look_at
        return math.degrees(math.atan2(-(ly - point.y), lx - point.x)) % 360.0
    if point.heading == "start":
        return math.degrees(math.atan2(point.y, -point.x)) % 360.0
    return None


def _int_params(values) -> Tuple[int, int, int]:
    """Współrzędne ``go_xyz_speed`` są całkowite (Tello przyjmuje int)."""
    return tuple(int(round(v)) for v in values)  # type: ignore[return-value]


def generate(route: Route) -> str:
    """Wygeneruj skrypt trybu „prosta” (czyste ``djitellopy``).

    :raises RouteError: gdy trasa jest pusta albo prędkość jest poza zakresem
        Tello (10-100 cm/s)
    """
    if not route.points:
        raise RouteError("Trasa jest pusta - dodaj przynajmniej jeden punkt.")

    moves: List[str] = []       # linie kodu ruchów (bez wcięcia)
    yaw = apply_turn(0.0, route.start_yaw_deg)   # kurs jak w get_yaw() (-180..180)

    def move(dx: float, dy: float, dz: float, point_index: int,
             legacy: bool = False) -> None:
        """``go_xyz_speed`` ze współrzędnymi w układzie AKTUALNEGO kursu drona."""
        point = route.points[point_index]
        speed = route.speed_for(point_index)
        if legacy:
            # jeden punkt: ruszamy wzdłuż osi ciała (go_xyz_speed wymaga x/y/z)
            vertical = int(round(dz))
            horizontal = int(round(math.hypot(dx, dy)))
            if abs(vertical) >= MIN_MOVE_CM:
                direction = "move_up" if vertical > 0 else "move_down"
                moves.append(f"tello.{direction}({abs(vertical)})"
                             f"   # punkt {point_index + 1}: wysokość {num(point.z)}")
            if horizontal >= MIN_MOVE_CM:
                step = body_move(dx, dy, yaw)
                if abs(step[1]) < 1e-6:
                    direction = "move_forward" if step[0] >= 0 else "move_back"
                else:                              # nieosiowy ruch rzadki: obrót + forward
                    direction = "move_forward"
                moves.append(f"tello.{direction}({horizontal})"
                             f"   # punkt {point_index + 1}: ({num(point.x)}, {num(point.y)})")
            return
        # go_xyz_speed liczy x/y w układzie nosa drona - rzutujemy przemieszczenie
        along, left = body_move(dx, dy, yaw)
        parts = split_segment(along, left, dz)
        for part_index, part in enumerate(parts, start=1):
            px, py, pz = _int_params(part)
            suffix = f" (cz. {part_index}/{len(parts)})" if len(parts) > 1 else ""
            moves.append(f"tello.go_xyz_speed({px}, {py}, {pz}, {int(round(speed))})"
                         f"   # punkt {point_index + 1}{suffix}: "
                         f"({num(point.x)}, {num(point.y)}, {num(point.z)})")

    def rotate(target: float, comment: str) -> None:
        """Obrót nosa w miejscu; ``yaw`` prowadzimy jak ``get_yaw()`` (-180..180)."""
        nonlocal yaw
        amount, direction = turn_command(yaw, target)
        if amount < 0.5:
            return
        method = "rotate_clockwise" if direction > 0 else "rotate_counter_clockwise"
        moves.append(f"tello.{method}({num(amount)})   # {comment}")
        yaw = apply_turn(yaw, amount if direction > 0 else -amount)

    def hover(seconds: float, comment: str) -> None:
        moves.append(f"time.sleep({num(seconds)})   # {comment}")

    segments = plan_segments(route)
    legacy_single = len(route.points) == 1
    for (dx, dy, dz), target_index in segments:
        point_index = target_index - 2                   # 0 = punkt 1 (0 to start)
        point = route.points[point_index]
        if (math.sqrt(dx * dx + dy * dy + dz * dz) < MIN_MOVE_CM - 1e-9
                and not moves):
            # pierwszy punkt bliżej niż 20 cm od startu - nie da się dolecieć osobnym ruchem
            hover(0.5, f"punkt {point_index + 1}: bliżej niż {num(MIN_MOVE_CM)} cm od "
                       f"startu - pomijam")
            continue
        speed = route.speed_for(point_index)
        if not (MIN_SPEED_CMS <= speed <= MAX_SPEED_CMS):
            raise RouteError(f"Punkt {point_index + 1}: prędkość {speed:.0f} cm/s jest "
                             f"poza zakresem Tello ({num(MIN_SPEED_CMS)}-{num(MAX_SPEED_CMS)}).")
        # go_xyz_speed liczy x/y w układzie AKTUALNEGO kursu drona - rzutujemy odcinek
        move(dx, dy, dz, point_index, legacy=legacy_single)
        if point.hover_s > 0:
            hover(point.hover_s, f"punkt {point_index + 1}: zawis {num(point.hover_s)} s")
        wanted = heading_target(route, point_index)
        if wanted is not None:
            kind = "stały kurs" if point.heading == "fixed" else "kurs na cel"
            rotate(wanted, f"punkt {point_index + 1}: {kind} {num(wanted)}°")

    if route.return_home:
        last = route.points[-1]
        back_x, back_y, back_z = -last.x, -last.y, 80.0 - last.z
        along, left = body_move(back_x, back_y, yaw)
        for part in split_segment(along, left, back_z):
            px, py, pz = _int_params(part)
            moves.append(f"tello.go_xyz_speed({px}, {py}, {pz}, "
                         f"{int(round(route.speed_for(len(route.points) - 1)))})"
                         f"   # powrót do startu (0, 0, 80)")

    lines: List[str] = [
        '"""Trasa drona - tryb prosty (czyste djitellopy).',
        "",
        "Wygenerowane przez DroneSim - Planer trasy.",
        "",
        "Układ: x = przód, y = lewo, z = góra (cm), start w (0, 0, 0).",
        "go_xyz_speed liczy x/y w układzie aktualnego kursu drona (x = przód,",
        "y = lewo), więc przemieszczenie każdego odcinka jest rzutowane na osie",
        "nosa. Obroty rotate_* (dodatni = w prawo) ustawiają kurs w punktach.",
        '"""',
        "",
        "import time",
        "",
        "from djitellopy import Tello",
        "from dronemoves.safety import safe_start",
        "",
        route_block(route, "simple"),
        "",
        "",
        "def main() -> None:",
        "    tello = Tello()",
        "    tello.connect()",
    ]
    lines.extend(battery_check())
    lines.extend([
        f"    tello.set_speed({int(round(route.default_speed))})"
        f"   # prędkość domyślna",
        "    yaw = 0.0   # kurs nosa w konwencji Tello (+ = w prawo)",
        "    try:",
    ])
    lines.extend(f"        {line}" for line in moves)
    lines.extend([
        "    finally:",
        "        # bezpieczne lądowanie także przy błędzie lub Ctrl+C",
        "        tello.land()",
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
        "",
    ])
    return "\n".join(lines)
