"""Walidacja trasy: limity Tello/dronemoves, kolizje ze sceną, estymacja lotu.

Wszystkie problemy mają ``index`` punktu (0 = start, N = punkt N) i ``leg``
(numer odcinka, 0 = dojazd do punktu 1), żeby UI mogło pokazać je przy
konkretnym punkcie/odcinku.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .model import (
    MAX_HEIGHT_CM, MAX_MOVE_CM, MAX_RADIUS_CM, MAX_SPEED_CMS, MIN_HEIGHT_CM,
    MIN_MOVE_CM, MIN_SPEED_CMS, TAKEOFF_HEIGHT_CM, Route,
)

#: kategorie problemów (UI pokazuje je różnymi kolorami)
LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"

#: dodatkowy czas na jeden obrót w miejscu (s) - start/stop, jak w symulatorze
ROTATE_OVERHEAD_S = 0.5
#: czas takeoff + lądowanie (s) - do szacowania czasu
TAKEOFF_S = 5.0
LAND_S = 5.0
#: zużycie baterii: lot i zawis (%/s) - jak w modelu Tello symulatora
BATTERY_FLIGHT_PCT_S = 0.05
BATTERY_IDLE_PCT_S = 0.002


def problem(level: str, message: str, index: int = 0, leg: int = 0,
            kind: str = "route") -> Dict[str, Any]:
    """Pojedynczy problem trasy (format dla UI)."""
    return {"level": level, "message": message, "index": index, "leg": leg, "kind": kind}


def direction_yaw(dx: float, dy: float) -> float:
    """Kurs nosa potrzebny, by osiowy ruch ``+x`` ciała prowadził w (dx, dy)."""
    return math.degrees(math.atan2(-dy, dx)) % 360.0


def turn_delta(yaw: float, target: float) -> float:
    """Najkrótszy obrót (-180..180, + = w prawo)."""
    return (target - yaw + 180.0) % 360.0 - 180.0


def heading_after(route: Route, index: int) -> float:
    """Kurs nosa po dojeździe do punktu ``index`` (konwencja Tello, + = prawo)."""
    point = route.points[index]
    start, end = route.legs()[index]
    if point.heading == "fixed":
        return point.yaw_deg % 360.0
    if point.heading == "point" and point.look_at is not None:
        lx, ly = point.look_at
        return math.degrees(math.atan2(-(ly - end[1]), lx - end[0])) % 360.0
    if point.heading == "start":
        return math.degrees(math.atan2(end[1], -end[0])) % 360.0
    dx, dy = end[0] - start[0], end[1] - start[1]
    return math.degrees(math.atan2(-dy, dx)) % 360.0


def straight_path(route: Route) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Trajektoria „jak w locie” w formacie telemetrii (samples, events).

    Liczona w układzie projektu (cm): start ``(0, 0, takeoff)``, potem odcinki
    do punktów. Kurs nosa: w trakcie odcinka skorygowany na jego kierunek
    (tryb „prosta” robi ``rotate_*`` przed ruchem), po dojeździe zgodny
    z ustawieniem punktu.

    :returns: ``(samples, events)`` - gotowe do ``analyse_flight`` funkcji przeszkód
    """
    samples: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    t = 0.0
    position = (0.0, 0.0, TAKEOFF_HEIGHT_CM)
    yaw = route.start_yaw_deg % 360.0
    samples.append({"t": 0.0, "x": position[0], "y": position[1],
                    "z": position[2], "yaw": -yaw})
    step = 2.0   # cm
    for leg_index, (start, end) in enumerate(route.legs()):
        dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        speed = route.speed_for(leg_index)
        if distance > 1e-9:
            yaw = direction_yaw(dx, dy)
        steps = max(2, int(math.ceil(distance / step)))
        duration = distance / speed if speed > 0 else 0.0
        events.append({"index": leg_index + 1, "command": "go_xyz_speed",
                       "args": [round(dx), round(dy), round(dz), int(round(speed))],
                       "t": round(t, 3), "t_end": round(t + duration, 3),
                       "line": None, "status": "ok"})
        for i in range(1, steps + 1):
            fraction = i / steps
            samples.append({
                "t": round(t + duration * fraction, 4),
                "x": start[0] + dx * fraction,
                "y": start[1] + dy * fraction,
                "z": start[2] + dz * fraction,
                "yaw": -yaw,          # telemetria: kurs wewnętrzny CCW+
            })
        t += duration
        position = end
        yaw = heading_after(route, leg_index)
        if route.points[leg_index].hover_s > 0:
            events.append({"index": leg_index + 1000, "command": "sleep",
                           "args": [route.points[leg_index].hover_s], "t": round(t, 3),
                           "t_end": round(t + route.points[leg_index].hover_s, 3),
                           "line": None, "status": "ok"})
            t += route.points[leg_index].hover_s
            samples.append({"t": round(t, 4), "x": position[0], "y": position[1],
                            "z": position[2], "yaw": -yaw})
    return samples, events


# ------------------------------------------------------------------- przewidywanie
def preview(route: Route) -> Dict[str, Any]:
    """Zaplanowany tor (dronemoves ``preview``) + numer i wysokość punktów.

    :returns: ``points`` (do rysowania), ``eta_s``, ``battery_pct``, ``distance_cm``
        - dla UI i tabeli wyników
    """
    points: List[Dict[str, Any]] = [{"index": 0, "x": 0.0, "y": 0.0,
                                     "z": TAKEOFF_HEIGHT_CM, "label": "start"}]
    t = TAKEOFF_S
    distance_cm = 0.0
    hover_s = 0.0
    yaw = route.start_yaw_deg % 360.0
    for leg_index, (start, end) in enumerate(route.legs()):
        leg = math.dist(start, end)
        speed = route.speed_for(leg_index)
        distance_cm += leg
        turn = abs(turn_delta(yaw, direction_yaw(end[0] - start[0], end[1] - start[1])))
        t += leg / speed + (ROTATE_OVERHEAD_S if turn > 1.0 else 0.0)
        yaw = heading_after(route, leg_index)
        hover_s += route.points[leg_index].hover_s
        t += route.points[leg_index].hover_s
        points.append({"index": leg_index + 1, "x": round(end[0], 1),
                       "y": round(end[1], 1), "z": round(end[2], 1),
                       "label": f"{leg_index + 1}"})
    if route.return_home and route.points:
        last = route.points[-1]
        back = math.hypot(last.x, last.y)
        distance_cm += back
        t += back / route.default_speed + ROTATE_OVERHEAD_S
    if route.land_at_end:
        t += LAND_S + (route.points[-1].z - 5.0) / 50.0 if route.points else LAND_S
    flight_s = max(0.0, t)
    battery = flight_s * BATTERY_FLIGHT_PCT_S + hover_s * BATTERY_IDLE_PCT_S
    return {"points": points, "eta_s": round(flight_s, 1),
            "battery_pct": round(battery, 1), "distance_cm": round(distance_cm, 1),
            "hover_s": round(hover_s, 1)}


# --------------------------------------------------------------------- walidacja
def validate(route: Route, scene: Optional[Dict[str, Any]] = None,
             margin_cm: Optional[float] = None) -> Dict[str, Any]:
    """Sprawdź trasę: limity Tello/dronemoves, kolizje i baterię.

    :param scene: scena przeszkód (format z funkcji „Przeszkody 3D”) - gdy
        ``None``, kontrola kolizji jest pomijana (planer działa samodzielnie)
    :param margin_cm: margines bezpieczeństwa dla kolizji (None = domyślny)
    :returns: ``{problems, stats, collisions}`` - lista problemów z indeksem punktu
    """
    problems: List[Dict[str, Any]] = []
    lengths = [math.dist(a, b) for a, b in route.legs()]
    for index, point in enumerate(route.points):
        number = index + 1
        if not (MIN_HEIGHT_CM <= point.z <= MAX_HEIGHT_CM):
            problems.append(problem(
                LEVEL_ERROR, f"Punkt {number}: wysokość {point.z:.0f} cm jest poza "
                             f"zakresem Tello ({MIN_HEIGHT_CM:.0f}-{MAX_HEIGHT_CM:.0f} cm).",
                number, number))
        radius = math.hypot(point.x, point.y)
        if radius > MAX_RADIUS_CM:
            problems.append(problem(
                LEVEL_ERROR, f"Punkt {number}: {radius:.0f} cm od startu przekracza limit "
                             f"dronemoves ({MAX_RADIUS_CM:.0f} cm).", number, number))
        speed = route.speed_for(index)
        if not (MIN_SPEED_CMS <= speed <= MAX_SPEED_CMS):
            problems.append(problem(
                LEVEL_ERROR, f"Punkt {number}: prędkość {speed:.0f} cm/s jest poza zakresem "
                             f"Tello ({MIN_SPEED_CMS:.0f}-{MAX_SPEED_CMS:.0f} cm/s).",
                number, number, "speed"))
        if lengths[index] < 1e-6 and point.hover_s <= 0 and index:
            problems.append(problem(
                LEVEL_WARNING, f"Punkt {number}: powtarza pozycję poprzedniego punktu.",
                number, number))

    if route.mode == "smooth":
        speeds = {route.speed_for(i) for i in range(len(route.points))}
        if len(speeds) > 1:
            problems.append(problem(
                LEVEL_ERROR, "Tryb „płynna” ma jedną prędkość na całą trasę - "
                             "usuń prędkości indywidualne albo wybierz tryb „prosta”.",
                0, 0, "mode"))
        if route.return_home:
            problems.append(problem(
                LEVEL_ERROR, "„Wróć do startu” działa tylko w trybie „prosta”.",
                0, 0, "mode"))

    # odcinki krótsze niż 20 cm: Tello wymaga 20-500 cm, łączymy je z sąsiednim
    for index, length in enumerate(lengths):
        if length >= MIN_MOVE_CM - 1e-9:
            continue
        prev_ok = index > 0 and lengths[index - 1] >= MIN_MOVE_CM - 1e-9
        next_ok = (index + 1 < len(lengths)
                   and lengths[index + 1] >= MIN_MOVE_CM - 1e-9)
        if prev_ok or next_ok:
            where = "poprzednim" if prev_ok else "następnym"
            problems.append(problem(
                LEVEL_WARNING,
                f"Punkt {index + 1}: odcinek {length:.0f} cm jest krótszy niż "
                f"{MIN_MOVE_CM:.0f} cm - zostanie połączony z {where} ruchem.",
                index + 1, index + 1, "merge"))
        else:
            problems.append(problem(
                LEVEL_ERROR,
                f"Punkt {index + 1}: odcinek {length:.0f} cm jest krótszy niż "
                f"{MIN_MOVE_CM:.0f} cm i nie ma sąsiedniego ruchu do sklejenia - "
                f"przesuń punkty.", index + 1, index + 1, "short"))

    # długie odcinki (Tello: max 500 cm na jeden ruch) - tylko informacja
    for index, length in enumerate(lengths):
        if length > MAX_MOVE_CM:
            parts = int(math.ceil(length / MAX_MOVE_CM))
            problems.append(problem(
                LEVEL_WARNING,
                f"Punkt {index + 1}: odcinek {length:.0f} cm - podzielony na {parts} "
                f"ruchów po ~{length / parts:.0f} cm (limit Tello {MAX_MOVE_CM:.0f} cm).",
                index + 1, index + 1, "split"))

    stats = preview(route)
    stats["legs_cm"] = [round(v, 1) for v in lengths]
    if stats["battery_pct"] > 80.0:
        problems.append(problem(
            LEVEL_ERROR, f"Szacowane zużycie baterii {stats['battery_pct']:.0f}% - "
                         f"za mało zapasu na start i lot.", 0, 0, "battery"))
    elif stats["battery_pct"] > 65.0:
        problems.append(problem(
            LEVEL_WARNING, f"Szacowane zużycie baterii {stats['battery_pct']:.0f}% - "
                           f"niewielki zapas po locie.", 0, 0, "battery"))

    collisions = check_collisions(route, scene, margin_cm) if scene else None
    if collisions:
        problems.extend(collisions["problems"])
    return {
        "problems": problems,
        "errors": sum(1 for p in problems if p["level"] == LEVEL_ERROR),
        "warnings": sum(1 for p in problems if p["level"] == LEVEL_WARNING),
        "stats": stats,
        "collisions": None if collisions is None else collisions["stats"],
        "collision_problems": None if collisions is None else len(collisions["problems"]),
    }


def _point_at_time(route: Route, t: float) -> int:
    """Numer punktu, do którego dojeżdża dron w chwili ``t`` (0 = przed punktem 1)."""
    clock = 0.0
    for index, (start, end) in enumerate(route.legs()):
        length = math.dist(start, end)
        clock += length / route.speed_for(index)
        if t <= clock + 1e-9:
            return index + 1
        clock += route.points[index].hover_s
    return len(route.points) if route.points else 0


def check_collisions(route: Route, scene: Dict[str, Any],
                     margin_cm: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Kontrola kolizji trasy ze sceną (``analyse_flight`` funkcji przeszkód).

    :returns: ``None``, gdy funkcja przeszkód jest wyłączona (wtedy planer
        działa bez kontroli kolizji - reszta walidacji bez zmian)
    """
    from .analyse import analyse_flight, available

    if not available():
        return None
    samples, events = straight_path(route)
    report = analyse_flight(samples, events, scene, margin_cm)
    from typing import Any, Dict

    problems: List[Dict[str, Any]] = []
    for finding in report.get("findings") or []:
        if finding.get("level") == "gate":
            continue
        t = float(finding.get("t") or 0.0)
        index = _point_at_time(route, t)
        collision = finding.get("level") == "collision"
        entry = problem(
            LEVEL_ERROR if collision else LEVEL_WARNING,
            f"Punkt {index}: {finding.get('message', '')}" if index
            else finding.get("message", ""),
            index, index, "collision" if collision else "clearance")
        entry["t"] = t
        problems.append(entry)
    return {"stats": report.get("stats") or {}, "problems": problems}
