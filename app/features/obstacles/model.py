"""Model danych przeszkód (funkcja ``obstacles``).

Układ współrzędnych projektu (patrz README, „Układ współrzędnych”):

* ``x`` = przód, ``y`` = lewo, ``z`` = góra, start drona w ``(0, 0, 0)``,
* wszystkie wymiary i pozycje w **centymetrach**,
* obrót obiektu ``yaw_deg`` wokół osi pionowej, **dodatni = w prawo** (konwencja
  Tello, taka sama jak w publicznym API ``dronemoves``).

Typy przeszkód:

* ``box`` - prostopadłościan (ściana, szafa, stół),
* ``cylinder`` - walec (słup, drzewo) o promieniu ``size[0] / 2``,
* ``gate`` - rama do przelotu (prostopadłościenna rama z otworem),
* ``plane`` - płaszczyzna (sufit / podłoga) - tylko do wyświetlania,
  nie bierze udziału w kolizjach ani w pomiarze odległości.

Pozycja to **środek bryły** ``(x, y, z)``; dla ``gate`` płaszczyzna ramy leży
w punkcie ``(x, y)`` i jest prostopadła do kierunku ``yaw_deg``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]

KINDS = ("box", "cylinder", "gate", "plane")
KIND_LABELS = {
    "box": "prostopadłościan",
    "cylinder": "walec",
    "gate": "bramka",
    "plane": "płaszczyzna",
}
#: gatunki z ``plane`` nie mają objętości - pomijane w kolizjach
SOLID_KINDS = ("box", "cylinder", "gate")


class SceneError(ValueError):
    """Niepoprawna scena lub przeszkoda (komunikat dla użytkownika)."""


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SceneError(f"Pole '{name}' musi być liczbą.") from None


def _as_triple(value: Any, name: str) -> Tuple[float, float, float]:
    """Trzy liczby (pozycja lub wymiary)."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise SceneError(f"Pole '{name}' musi być listą trzech liczb [x, y, z].")
    return tuple(_as_float(v, name) for v in value)  # type: ignore[return-value]


def _as_size(value: Any, name: str = "size") -> Tuple[float, float, float]:
    """Trzy liczby dodatnie (wymiary)."""
    size = _as_triple(value, name)
    if min(size) <= 0:
        raise SceneError("Wymiary przeszkody muszą być dodatnie.")
    return size


@dataclass
class Obstacle:
    """Jedna przeszkoda w scenie."""

    kind: str = "box"
    name: str = ""
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: Tuple[float, float, float] = (100.0, 10.0, 100.0)
    yaw_deg: float = 0.0
    #: otwór bramki ``(szerokość, wysokość)`` - środek otworu = środek ramy
    opening: Tuple[float, float] = (50.0, 50.0)
    #: grubość ramy bramki / płaszczyzny (cm)
    thickness: float = 5.0
    id: str = ""

    def __post_init__(self) -> None:
        self.kind = str(self.kind).lower()
        if self.kind not in KINDS:
            raise SceneError(f"Nieznany typ przeszkody: {self.kind!r}.")
        self.position = _as_triple(self.position, "position")
        self.size = _as_size(self.size)
        self.yaw_deg = _as_float(self.yaw_deg, "yaw_deg") % 360.0
        opening = self.opening if isinstance(self.opening, (list, tuple)) else (50, 50)
        if len(opening) != 2:
            raise SceneError("Pole 'opening' musi być parą [szerokość, wysokość].")
        self.opening = (_as_float(opening[0], "opening"), _as_float(opening[1], "opening"))
        if min(self.opening) <= 0:
            raise SceneError("Otwór bramki musi mieć dodatnie wymiary.")
        self.thickness = _as_float(self.thickness, "thickness")
        if self.thickness <= 0:
            raise SceneError("Grubość musi być dodatnia.")
        if not self.name:
            self.name = KIND_LABELS[self.kind]

    # ------------------------------------------------------------ właściwości
    @property
    def solid(self) -> bool:
        """Czy przeszkoda bierze udział w kolizjach."""
        return self.kind in SOLID_KINDS

    @property
    def yaw_rad(self) -> float:
        """Obrót w radianach (dodatni = w prawo, zgodnie z ruchem wskazówek)."""
        return math.radians(self.yaw_deg)

    @property
    def local_axes(self) -> Tuple[Vec2, Vec2]:
        """Osie lokalne bryły w układzie projektu.

        ``(normalna, szerokość)``:

        * normalna (lokalne ``x``) - kierunek „przodu” bryły, dla bramki
          prostopadły do płaszczyzny ramy,
        * szerokość (lokalne ``y``) - kierunek wzdłuż ramy, na lewo od normalnej.

        Bryła o ``yaw_deg = 0`` ma normalną ``(1, 0)`` (oś ``+x`` projektu) i
        szerokość ``(0, 1)`` (oś ``+y`` = lewo). Obrót „w prawo” (zgodnie z
        zegarem) dla ``yaw = 90`` daje normalną ``(0, -1)``.
        """
        c, s = math.cos(self.yaw_rad), math.sin(self.yaw_rad)
        return (c, s), (-s, c)

    def to_world(self, local: Vec2) -> Vec2:
        """Punkt w układzie bryły (przód, lewo) -> współrzędne projektu."""
        (fx, fy), (lx, ly) = self.local_axes
        return (self.position[0] + fx * local[0] + lx * local[1],
                self.position[1] + fy * local[0] + ly * local[1])

    def to_local(self, point: Vec2) -> Vec2:
        """Współrzędne projektu -> układ bryły (przód, lewo)."""
        (fx, fy), (lx, ly) = self.local_axes
        dx = point[0] - self.position[0]
        dy = point[1] - self.position[1]
        return (dx * fx + dy * fy, dx * lx + dy * ly)

    @property
    def z_range(self) -> Tuple[float, float]:
        """Zakres wysokości bryły (dolna, górna)."""
        half = self.size[2] / 2.0
        if self.kind == "plane":
            return (self.position[2] - self.thickness / 2.0,
                    self.position[2] + self.thickness / 2.0)
        return (self.position[2] - half, self.position[2] + half)

    @property
    def radius(self) -> float:
        """Promień walca (dla pozostałych typów: połowa przekątnej podstawy)."""
        if self.kind == "cylinder":
            return self.size[0] / 2.0
        return math.hypot(self.size[0], self.size[1]) / 2.0

    # -------------------------------------------------------------- zapis/odczyt
    def as_dict(self) -> Dict[str, Any]:
        """Słownik zgodny z formatem JSON sceny."""
        data: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "position": [round(v, 3) for v in self.position],
            "size": [round(v, 3) for v in self.size],
            "yaw_deg": round(self.yaw_deg, 3),
        }
        if self.kind == "gate":
            data["opening"] = [round(v, 3) for v in self.opening]
            data["thickness"] = round(self.thickness, 3)
        elif self.kind == "plane":
            data["thickness"] = round(self.thickness, 3)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Obstacle":
        """Zbuduj przeszkodę ze słownika JSON (walidacja pól)."""
        if not isinstance(data, dict):
            raise SceneError("Przeszkoda musi być obiektem JSON.")
        return cls(
            kind=data.get("kind", "box"),
            name=str(data.get("name") or ""),
            position=data.get("position", (0, 0, 0)),
            size=data.get("size", (100, 10, 100)),
            yaw_deg=data.get("yaw_deg", 0),
            opening=data.get("opening", (50, 50)),
            thickness=data.get("thickness", 5),
            id=str(data.get("id") or ""),
        )


@dataclass
class Scene:
    """Scena przeszkód: nazwa, wymiary pomieszczenia i lista przeszkód."""

    name: str = "Nowa scena"
    description: str = ""
    room: Optional[Tuple[float, float, float]] = None
    obstacles: List[Obstacle] = field(default_factory=list)

    def by_id(self, obstacle_id: str) -> Optional[Obstacle]:
        for obstacle in self.obstacles:
            if obstacle.id == obstacle_id:
                return obstacle
        return None

    def solids(self) -> List[Obstacle]:
        """Przeszkody biorące udział w kolizjach."""
        return [o for o in self.obstacles if o.solid]

    def gates(self) -> List[Obstacle]:
        return [o for o in self.obstacles if o.kind == "gate"]

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "format": "dronesim-scene",
            "version": 1,
            "name": self.name,
            "description": self.description,
            "obstacles": [o.as_dict() for o in self.obstacles],
        }
        if self.room:
            data["room"] = [round(v, 3) for v in self.room]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scene":
        if not isinstance(data, dict):
            raise SceneError("Scena musi być obiektem JSON.")
        raw = data.get("obstacles") or []
        if not isinstance(raw, list):
            raise SceneError("Pole 'obstacles' musi być listą.")
        room = data.get("room")
        room_tuple: Optional[Tuple[float, float, float]] = None
        if isinstance(room, (list, tuple)) and len(room) == 3:
            room_tuple = _as_size(room)
        return cls(
            name=str(data.get("name") or "Scena"),
            description=str(data.get("description") or ""),
            room=room_tuple,
            obstacles=[Obstacle.from_dict(item) for item in raw],
        )

    def copy(self, name: Optional[str] = None) -> "Scene":
        """Kopia sceny (identyfikatory przeszkód zostają te same)."""
        data = self.as_dict()
        if name:
            data["name"] = name
        return Scene.from_dict(data)


# ------------------------------------------------------------------ geometria 2D
def dist_point_to_segment(point: Vec2, start: Vec2, end: Vec2) -> float:
    """Odległość punktu od odcinka."""
    ax, ay = start
    bx, by = end
    px, py = point
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _orient(p: Vec2, q: Vec2, r: Vec2) -> float:
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def _on_segment(p: Vec2, q: Vec2, r: Vec2) -> bool:
    return (min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
            and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9)


def segments_cross(a1: Vec2, a2: Vec2, b1: Vec2, b2: Vec2) -> bool:
    """Czy odcinki ``a1-a2`` i ``b1-b2`` przecinają się **właściwie**.

    Styk końców (wierzchołek jednego na końcu drugiego) nie jest przecięciem -
    dla rzutów brył to sytuacja „obok siebie”, nie „nachodzą na siebie”.
    """
    d1 = _orient(b1, b2, a1)
    d2 = _orient(b1, b2, a2)
    d3 = _orient(a1, a2, b1)
    d4 = _orient(a1, a2, b2)
    return ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and \
        ((d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9))


def point_in_polygon(point: Vec2, polygon: Sequence[Vec2]) -> bool:
    """Czy punkt jest wewnątrz wielokąta (algorytm promienia)."""
    x, y = point
    inside = False
    count = len(polygon)
    for i in range(count):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % count]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def polygon_crosses_segment(polygon: Sequence[Vec2], start: Vec2, end: Vec2) -> bool:
    """Czy odcinek przecina obrys wielokąta albo leży w całości w środku."""
    count = len(polygon)
    for i in range(count):
        if segments_cross(polygon[i], polygon[(i + 1) % count], start, end):
            return True
    return point_in_polygon(start, polygon)


def segment_distance_2d(start: Vec2, end: Vec2, polygon: Sequence[Vec2]) -> float:
    """Najmniejsza odległość odcinka od wielokąta (0, gdy się przecinają)."""
    if polygon_crosses_segment(polygon, start, end):
        return 0.0
    best = math.inf
    count = len(polygon)
    for i in range(count):
        a = polygon[i]
        b = polygon[(i + 1) % count]
        best = min(best, dist_point_to_segment(start, a, b), dist_point_to_segment(end, a, b),
                   dist_point_to_segment(a, start, end), dist_point_to_segment(b, start, end))
    return best


def rect_distance_sdf(local: Vec2, size: Vec2) -> float:
    """Odległość 2D punktu (układ bryły) od prostokąta ``±size/2`` (0 w środku)."""
    qx = abs(local[0]) - size[0] / 2.0
    qy = abs(local[1]) - size[1] / 2.0
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return outside + inside
