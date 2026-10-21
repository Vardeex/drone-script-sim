"""Analiza lotu względem przeszkód (kolizje, zbliżenia, bramki).

Dron to prostopadłościan ``10 x 10 x 5 cm`` (szerokość x długość x wysokość),
obracany kursem wokół osi pionowej, powiększony o **margines bezpieczeństwa**.
Sprawdzana jest **cała telemetria**, a nie tylko próbki: między kolejnymi
próbkami pozycja jest interpolowana co ``SAMPLE_STEP_CM`` centymetrów, więc
szybki przelot nie „przeskoczy” cienkiej ściany.

Przeszkody nie wpływają na przebieg symulacji - funkcja tylko raportuje, że
skrypt rozbiłby drona. Wynik trafia do lotu (``payload["obstacles"]``) jako
wpisy na liście problemów i znaczniki na trasie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .model import (Obstacle, Scene, dist_point_to_segment, point_in_polygon)

#: wymiary drona - prostopadłościan (szerokość, długość, wysokość) w cm
DRONE_WIDTH = 10.0
DRONE_LENGTH = 10.0
DRONE_HEIGHT = 5.0
#: domyślny margines bezpieczeństwa (cm)
DEFAULT_MARGIN = 20.0
#: krok próbkowania trasy między próbkami telemetrii (cm)
SAMPLE_STEP_CM = 1.0
#: minimalna liczba dodatkowych punktów między próbkami (dla bardzo wolnego lotu)
MIN_SUBSTEPS = 2
#: tolerancja „środka” bramki - dron musi zmieścić się z tym zapasem od ramy (cm)
GATE_CENTER_TOLERANCE = 2.0
#: szerokość okna (cm) do wyznaczenia kierunku lotu przy przelocie przez bramkę.
#: Musi być mała (1-2 punkty trasy), inaczej do kierunku wliczają się skręty.
GATE_SAMPLE_WINDOW_CM = 2.0 * SAMPLE_STEP_CM


#: kolejność poziomów przy sortowaniu wpisów o tym samym czasie (kolizja pierwsza)
_LEVEL_ORDER = {"collision": 0, "gate": 1, "warning": 2}


@dataclass
class Finding:
    """Pojedyncze odkrycie: kolizja, ostrzeżenie (zbliżenie) lub bramka."""

    level: str            # collision | warning | gate
    t: float              # czas zdarzenia (s symulacji)
    t_end: float
    obstacle_id: str
    obstacle_name: str
    distance_cm: float    # odstęp drona (po odjęciu marginesu); 0 przy kolizji
    message: str
    event_index: Optional[int] = None   # indeks komendy w telemetrii (jeśli znany)
    line: Optional[int] = None          # linia skryptu komendy
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "t": round(self.t, 3),
            "t_end": round(self.t_end, 3),
            "obstacle_id": self.obstacle_id,
            "obstacle_name": self.obstacle_name,
            "distance_cm": round(self.distance_cm, 2),
            "message": self.message,
            "event_index": self.event_index,
            "line": self.line,
            "position": [round(v, 2) for v in self.position],
        }


# ------------------------------------------------------------------ geometria 3D
def _box_footprint(cx: float, cy: float, yaw_internal: float,
                   width: float, length: float) -> List[Tuple[float, float]]:
    """Rzut drona na podłoże (4 wierzchołki) w układzie projektu.

    :param yaw_internal: kurs wewnętrzny drona w stopniach (dodatni = w lewo)

    Układ projektu ma ``y`` = lewo; kurs wewnętrzny (CCW+) daje przód
    ``(cos, sin)`` i lewą stronę ``(-sin, cos)``.
    """
    rad = math.radians(yaw_internal)
    fx, fy = math.cos(rad), math.sin(rad)      # kierunek przodu
    lx, ly = -math.sin(rad), math.cos(rad)     # kierunek w lewo (bok)
    hl, hw = length / 2.0, width / 2.0
    return [(cx + fx * a + lx * s, cy + fy * a + ly * s)
            for a, s in ((hl, hw), (-hl, hw), (-hl, -hw), (hl, -hw))]


def _box_center_distance(footprint: Sequence[Tuple[float, float]],
                         obstacle: Obstacle) -> float:
    """Odległość 2D między rzutami drona i przeszkody (0 = rzuty nachodzą)."""
    if obstacle.kind == "cylinder":
        cx, cy = obstacle.position[0], obstacle.position[1]
        if point_in_polygon((cx, cy), footprint):
            return 0.0
        nearest = min(dist_point_to_segment((cx, cy), footprint[i],
                                            footprint[(i + 1) % len(footprint)])
                      for i in range(len(footprint)))
        return max(0.0, nearest - obstacle.radius)

    # prostopadłościan / rama bramki: rzuty to dwa prostokąty (dron i bryła)
    local = [obstacle.to_local(corner) for corner in footprint]
    hx, hy = obstacle.size[0] / 2.0, obstacle.size[1] / 2.0
    box = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    if _overlap_distance(local, box) > 0.0:
        return 0.0
    best = math.inf
    for i in range(4):
        a, b = local[i], local[(i + 1) % 4]
        for j in range(4):
            c, d = box[j], box[(j + 1) % 4]
            best = min(best, dist_point_to_segment(a, c, d), dist_point_to_segment(c, a, b))
    return best


def _overlap_distance(poly1: Sequence[Tuple[float, float]],
                      poly2: Sequence[Tuple[float, float]]) -> float:
    """SAT: największe rozsunięcie rzutów wypukłych; ``> 0`` = nachodzą."""
    best = math.inf
    for poly in (poly1, poly2):
        for i in range(len(poly)):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % len(poly)]
            normal = (y1 - y2, x2 - x1)      # normalna krawędzi (dowolna długość)
            length = math.hypot(normal[0], normal[1])
            if length < 1e-12:
                continue
            normal = (normal[0] / length, normal[1] / length)
            proj1 = [p[0] * normal[0] + p[1] * normal[1] for p in poly1]
            proj2 = [p[0] * normal[0] + p[1] * normal[1] for p in poly2]
            gap = min(max(proj1) - min(proj2), max(proj2) - min(proj1))
            best = min(best, gap)
    return best


def drone_distance(pos: Sequence[float], yaw_internal: float, obstacle: Obstacle,
                   margin: float = DEFAULT_MARGIN) -> float:
    """Odległość drona od przeszkody: ``< 0`` = kolizja, ``0..margin`` = zbliżenie.

    Wartość dodatnia to odstęp od powiększonej bryły (margines już odjęty).
    Płaszczyzny (``plane``) są pomijane - zwracają ``inf``.
    """
    if not obstacle.solid:
        return math.inf
    if obstacle.kind == "gate":
        return _gate_distance(pos, yaw_internal, obstacle) - margin
    low = obstacle.position[2] - obstacle.size[2] / 2.0
    high = obstacle.position[2] + obstacle.size[2] / 2.0
    drone_low = pos[2] - DRONE_HEIGHT / 2.0
    drone_high = pos[2] + DRONE_HEIGHT / 2.0
    dz = max(low - drone_high, drone_low - high, 0.0)
    footprint = _box_footprint(pos[0], pos[1], yaw_internal, DRONE_WIDTH, DRONE_LENGTH)
    dxy = _box_center_distance(footprint, obstacle)
    return math.hypot(dxy, dz) - margin


def _gate_distance(pos: Sequence[float], yaw_internal: float, gate: Obstacle) -> float:
    """Odległość drona od konstrukcji ramy bramki (bez marginesu).

    Rama to obrys ``size`` z prostokątnym otworem ``opening`` - dron w otworze
    jest „wewnątrz”, więc odległość liczymy od krawędzi otworu.
    """
    low = gate.position[2] - gate.size[2] / 2.0
    high = gate.position[2] + gate.size[2] / 2.0
    drone_low = pos[2] - DRONE_HEIGHT / 2.0
    drone_high = pos[2] + DRONE_HEIGHT / 2.0
    dz = max(low - drone_high, drone_low - high, 0.0)
    half_depth = gate.size[1] / 2.0
    corners = _box_footprint(pos[0], pos[1], yaw_internal, DRONE_WIDTH, DRONE_LENGTH)
    local = [gate.to_local(corner) for corner in corners]
    depth = max(abs(p[0]) for p in local)
    if depth <= half_depth:
        # dron w płaszczyźnie ramy: liczy się odległość od krawędzi otworu
        half_open_x = gate.opening[0] / 2.0
        half_open_z = gate.opening[1] / 2.0
        worst = max(max(abs(p[1]) for p in local) - half_open_x,
                    abs(pos[2] - gate.position[2]) + DRONE_HEIGHT / 2.0 - half_open_z)
        return max(0.0, worst)
    dx = max(0.0, depth - half_depth)
    frame_low = gate.position[2] - gate.size[2] / 2.0
    frame_high = gate.position[2] + gate.size[2] / 2.0
    inside_frame = frame_low <= pos[2] <= frame_high
    lateral = max(abs(p[1]) for p in local)
    if inside_frame and lateral <= gate.size[0] / 2.0:
        return dx
    return math.hypot(dx, dz)


# --------------------------------------------------------------------- trasa
def _interpolate(samples: Sequence[Dict[str, Any]]) -> List[Tuple[float, float, float, float]]:
    """Punkty trasy ``(t, x, y, z, yaw_internal)`` z próbek telemetrii.

    Między próbkami dodawane są punkty co ``SAMPLE_STEP_CM`` centymetrów, aby
    żaden fragment trasy nie został pominięty (np. cienka ściana).
    """
    if not samples:
        return []
    points: List[Tuple[float, float, float, float]] = []
    first = samples[0]
    points.append((float(first["t"]), float(first["x"]), float(first["y"]), float(first["z"]),
                   float(first.get("yaw", 0.0))))
    for previous, current in zip(samples, samples[1:]):
        t0, t1 = float(previous["t"]), float(current["t"])
        dx = float(current["x"]) - float(previous["x"])
        dy = float(current["y"]) - float(previous["y"])
        dz = float(current["z"]) - float(previous["z"])
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        steps = max(MIN_SUBSTEPS, int(math.ceil(distance / SAMPLE_STEP_CM)))
        dyaw = ((float(current.get("yaw", 0.0)) - float(previous.get("yaw", 0.0)) + 180.0)
                % 360.0) - 180.0
        for step in range(1, steps + 1):
            frac = step / steps
            # punkt wypadający dokładnie w środku odcinka przesuwamy o ułamek
            # kroku - inaczej trafia idealnie w płaszczyznę ramki (np. x = 150)
            # i „zjada” przelot przez bramkę
            if steps % 2 == 0 and step == steps // 2:
                frac += 0.25 / steps
            points.append((
                t0 + (t1 - t0) * frac,
                float(previous["x"]) + dx * frac,
                float(previous["y"]) + dy * frac,
                float(previous["z"]) + dz * frac,
                float(previous.get("yaw", 0.0)) + dyaw * frac,
            ))
    return points


def _find_event(events: Sequence[Dict[str, Any]], t: float) -> Optional[Dict[str, Any]]:
    """Komenda aktywna w chwili ``t`` (ostatnia rozpoczęta do tej chwili)."""
    found: Optional[Dict[str, Any]] = None
    for event in events:
        start = float(event.get("t") or 0.0)
        end = float(event.get("t_end") if event.get("t_end") is not None else start)
        if start <= t + 1e-9:
            found = event
            if end >= t - 1e-9:
                break
        else:
            break
    return found


def _gate_pass(x: float, y: float, yaw_internal: float, gate: Obstacle) -> str:
    """Ocena drona przechodzącego przez płaszczyznę ramy w punkcie ``(x, y)``."""
    corners = _box_footprint(x, y, yaw_internal, DRONE_WIDTH, DRONE_LENGTH)
    lateral = max(abs(gate.to_local((cx, cy))[1]) for cx, cy in corners)
    return "clean" if lateral <= gate.opening[0] / 2.0 - GATE_CENTER_TOLERANCE else "touch"


def _gate_side(point: Tuple[float, float, float, float], gate: Obstacle) -> float:
    """Strona płaszczyzny ramy: ``-1`` przed, ``1`` za."""
    local = gate.to_local((point[1], point[2]))[0]
    return 1.0 if local > 0 else -1.0


def _assess_passage(points: Sequence[Tuple[float, float, float, float]], gate: Obstacle,
                    before: int, after: int) -> Optional[str]:
    """Ocena przelotu przez bramkę między punktami ``before`` i ``after``.

    ``None`` = dron przeleciał ponad/pod otworem (albo minął bramkę bokiem).
    W przeciwnym razie ``"clean"`` albo ``"touch"``.

    Kierunek lotu liczymy z okna ±``GATE_SAMPLE_WINDOW_CM`` wokół przecięcia.
    Dzięki temu zatrzymanie drona w płaszczyźnie ramy i zjazd boczny nie
    zmieniają oceny samego przelotu.
    """
    p_before = points[before]
    p_after = points[after]
    x0 = gate.to_local((p_before[1], p_before[2]))[0]
    x1 = gate.to_local((p_after[1], p_after[2]))[0]
    if abs(x1 - x0) < 1e-9:
        return None
    frac = x0 / (x0 - x1)
    crossing_x = p_before[1] + (p_after[1] - p_before[1]) * frac
    crossing_y = p_before[2] + (p_after[2] - p_before[2]) * frac
    crossing_z = p_before[3] + (p_after[3] - p_before[3]) * frac
    if abs(crossing_z - gate.position[2]) + DRONE_HEIGHT / 2.0 > gate.opening[1] / 2.0:
        return None      # przejście nad/pod otworem

    # kierunek lotu: od punktu najbliższego `window` cm przed ramą do za ramą
    window = GATE_SAMPLE_WINDOW_CM
    head = before
    while head > 0 and abs(gate.to_local((points[head][1], points[head][2]))[0]) < window:
        head -= 1
    tail = after
    while tail < len(points) - 1 and \
            abs(gate.to_local((points[tail][1], points[tail][2]))[0]) < window:
        tail += 1
    dx = points[tail][1] - points[head][1]
    dy = points[tail][2] - points[head][2]
    if math.hypot(dx, dy) < 1e-9:
        return None
    # dron musi faktycznie lecieć w poprzek ramy (a nie zjeżdżać wzdłuż niej)
    (nx, ny), (tx, ty) = gate.local_axes
    if abs(dx * nx + dy * ny) <= abs(dx * tx + dy * ty):
        return None
    lateral = gate.to_local((crossing_x, crossing_y))[1]
    if abs(lateral) > gate.size[0] / 2.0:
        return None      # dron minął bramkę bokiem, poza ramą
    return _gate_pass_at(lateral, gate, dx, dy)


def _gate_pass_at(lateral: float, gate: Obstacle, dx: float, dy: float) -> str:
    """Czy dron mieści się w otworze, przecinając ramę w punkcie bocznym ``lateral``.

    :param lateral: odległość punktu przecięcia od środka ramy, mierzona
        **wzdłuż** ramy (lokalna współrzędna ``y`` bramki, cm)
    :param dx, dy: kierunek lotu w układzie projektu (globalne ``x``, ``y``)
    """
    # kierunek lotu w układzie bramki: osie to (normalna ramy, szerokość ramy)
    (nx, ny), (tx, ty) = gate.local_axes
    along = dx * nx + dy * ny        # w poprzek ramy (wzdłuż normalnej)
    sideways = dx * tx + dy * ty     # wzdłuż ramy (w szerokości otworu)
    length = math.hypot(along, sideways)
    if length < 1e-9:
        return "touch"
    cos_angle = abs(along) / length          # 1 = lot prostopadle do ramy
    sin_angle = abs(sideways) / length
    # rzut drona (prostopadłościan 10 x 10 cm) na kierunek wzdłuż ramy
    half_extent = (DRONE_WIDTH / 2.0) * cos_angle + (DRONE_LENGTH / 2.0) * sin_angle
    return "clean" if abs(lateral) + half_extent <= gate.opening[0] / 2.0 - GATE_CENTER_TOLERANCE \
        else "touch"


def _scan_gate(points: Sequence[Tuple[float, float, float, float]],
               gate: Obstacle) -> List[Tuple[float, int, int, Optional[str]]]:
    """Znajdź wszystkie przeloty trasy przez bramkę.

    Przelot = trasa przechodzi z jednej strony płaszczyzny ramy na drugą.
    Ocena liczona jest w punkcie przecięcia, z kierunkiem lotu wyznaczonym
    lokalnie (okno ±``GATE_SAMPLE_WINDOW_CM``), więc prędkość lotu, „trafienie”
    próbką w ramę czy zjazd boczny w płaszczyźnie ramy nie zmieniają wyniku.

    :returns: lista ``(t, i_start, i_end, ocena)`` - ``ocena`` to ``"clean"``,
        ``"touch"`` albo ``None`` (dron przeleciał ponad/pod bramką)
    """
    local = [gate.to_local((p[1], p[2]))[0] for p in points]

    # przecięcia płaszczyzny ramy (w obie strony) - jedno przejście to jedno
    # przecięcie; pobyt drona w płaszczyźnie ramy obsługuje _assess_passage
    passages: List[Tuple[float, int, int, Optional[str]]] = []
    for index in range(len(points) - 1):
        if (local[index] > 0) == (local[index + 1] > 0):
            continue
        result = _assess_passage(points, gate, index, index + 1)
        if result is None:
            continue
        passages.append((points[index + 1][0], index, index + 1, result))
    return passages


# --------------------------------------------------------------- analiza lotu
def _group(findings: List[Finding]) -> List[Finding]:
    """Scal kolejne odkrycia tego samego poziomu dla tej samej przeszkody."""
    grouped: List[Finding] = []
    for finding in findings:
        last = grouped[-1] if grouped else None
        if (last is not None and last.level == finding.level
                and last.obstacle_id == finding.obstacle_id
                and finding.t - last.t_end <= 0.25 and last.level != "gate"):
            last.t_end = max(last.t_end, finding.t_end)
            last.distance_cm = min(last.distance_cm, finding.distance_cm)
            continue
        grouped.append(Finding(**{**finding.__dict__}))
        grouped[-1].t_end = finding.t
    return grouped


def analyse_flight(samples: Sequence[Dict[str, Any]], events: Sequence[Dict[str, Any]],
                   scene_dict: Optional[Dict[str, Any]],
                   margin: float = DEFAULT_MARGIN) -> Dict[str, Any]:
    """Przeanalizuj cały lot względem sceny przeszkód.

    :param samples: telemetria lotu (format ``Simulation``/``storage``)
    :param events: komendy (``command``, ``args``, ``t``, ``t_end``, ``line``, ...)
    :param scene_dict: scena w formacie JSON (``None`` = brak przeszkód)
    :param margin: margines bezpieczeństwa w cm
    :returns: słownik zapisywany w locie pod kluczem ``obstacles``

    Konwencja: próbki telemetrii mają kurs **wewnętrzny** (CCW+, dodatni =
    w lewo) - w tym samym układzie są przeszkody (czysta geometria, bez API).
    """
    scene = Scene.from_dict(scene_dict) if scene_dict else Scene(obstacles=[])
    margin = max(0.0, float(margin))
    findings: List[Finding] = []
    min_distance = math.inf          # NAJMNIEJSZY odstęp (bez marginesu)
    min_entry: Optional[Finding] = None

    points = _interpolate(samples)
    solids = [o for o in scene.solids() if o.kind != "gate"]
    gates = scene.gates()

    was_inside = {id(o): False for o in solids}
    for index, point in enumerate(points):
        t, x, y, z, yaw = point
        pos = (x, y, z)
        for obstacle in solids:
            distance = drone_distance(pos, yaw, obstacle, margin)
            clearance = distance + margin          # odstęp od powierzchni (bez marginesu)
            if clearance < min_distance:
                min_distance = clearance
                event = _find_event(events, t)
                min_entry = Finding(
                    level="warning", t=t, t_end=t, obstacle_id=obstacle.id or obstacle.name,
                    obstacle_name=obstacle.name, distance_cm=max(0.0, clearance),
                    message="", event_index=event.get("index") if event else None,
                    line=event.get("line") if event else None, position=pos)
            if distance <= 0.0:
                # dron dotyka przeszkody - jeden wpis na całe wejście w bryłę
                if not was_inside[id(obstacle)]:
                    was_inside[id(obstacle)] = True
                    findings.append(_entry("collision", t, obstacle, 0.0, pos,
                                           _find_event(events, t), margin))
                continue
            if distance > margin:
                was_inside[id(obstacle)] = False
                continue
            findings.append(_entry("warning", t, obstacle, distance, pos,
                                   _find_event(events, t), margin))
        # rama bramki: minimalna odległość od krawędzi otworu (bez marginesu
        # bezpieczeństwa - dron ma wręcz przelecieć przez otwór)
        for gate in gates:
            distance = _gate_distance(pos, yaw, gate)
            if distance < min_distance:
                min_distance = distance
                event = _find_event(events, t)
                min_entry = Finding(
                    level="warning", t=t, t_end=t, obstacle_id=gate.id or gate.name,
                    obstacle_name=gate.name, distance_cm=distance,
                    message="", event_index=event.get("index") if event else None,
                    line=event.get("line") if event else None, position=pos)
        # przelot przez bramkę: ocena po zebraniu całej trasy (patrz niżej)
    # przeloty przez bramki - cała trasa naraz (odporne na zaokrąglenia telemetrii)
    for gate in gates:
        for t_cross, start, end, result in _scan_gate(points, gate):
            event = _find_event(events, t_cross)
            position = (points[start][1], points[start][2], points[start][3])
            if result == "clean":
                findings.append(_entry("gate", t_cross, gate, 0.0, position, event, margin))
            elif result == "touch":
                findings.append(_entry(
                    "collision", t_cross, gate, 0.0, position, event, margin,
                    message=f"Kolizja z ramą bramki „{gate.name}” - dron nie zmieścił "
                            f"się w otworze."))
    grouped = _group(sorted(findings, key=lambda f: (f.t, _LEVEL_ORDER.get(f.level, 9))))
    stats = {
        "collisions": sum(1 for f in grouped if f.level == "collision"),
        "warnings": sum(1 for f in grouped if f.level == "warning"),
        "gates_passed": sum(1 for f in grouped if f.level == "gate"),
        "gates_total": len(gates),
        "min_distance_cm": None if not math.isfinite(min_distance) else round(min_distance, 2),
        "margin_cm": round(margin, 2),
    }
    if min_entry is not None:
        min_entry.t_end = min_entry.t
        stats["min_distance_t"] = round(min_entry.t, 3)
        stats["min_distance_obstacle"] = min_entry.obstacle_name
    return {
        "format": "dronesim-obstacle-report",
        "version": 1,
        "scene": scene.as_dict(),
        "drone_size_cm": [DRONE_WIDTH, DRONE_LENGTH, DRONE_HEIGHT],
        "stats": stats,
        "findings": [f.as_dict() for f in grouped],
    }


def _entry(level: str, t: float, obstacle: Obstacle, distance: float,
           pos: Sequence[float], event: Optional[Dict[str, Any]], margin: float,
           message: Optional[str] = None) -> Finding:
    """Zbuduj wpis z komunikatem po polsku."""
    name = obstacle.name
    if level == "collision":
        text = message or f"Kolizja z przeszkodą „{name}”."
    elif level == "warning":
        text = (message or f"Zbliżenie do przeszkody „{name}”: "
                f"{max(0.0, distance):.1f} cm od marginesu bezpieczeństwa "
                f"({margin:.0f} cm).")
    else:
        text = message or f"Przelot przez bramkę „{name}” zaliczony."
    return Finding(
        level=level, t=t, t_end=t, obstacle_id=obstacle.id or name,
        obstacle_name=name, distance_cm=max(0.0, distance), message=text,
        event_index=event.get("index") if event else None,
        line=event.get("line") if event else None, position=(pos[0], pos[1], pos[2]))
