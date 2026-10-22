"""Model trasy: punkty, opcje, walidacja liczb i blok-znacznik w skrypcie.

Układ współrzędnych projektu (README, „Układ współrzędnych”):

* ``x`` = przód, ``y`` = lewo, ``z`` = góra, start drona w ``(0, 0, 0)``,
* wszystkie wartości w **centymetrach**,
* kurs nosa ``yaw_deg`` w konwencji publicznej (Tello / dronemoves):
  **dodatni = w prawo** (zgodnie z ruchem wskazówek zegara patrząc z góry).

Trasa to lista punktów; każdy punkt opisuje **dojazd do niego** (odcinek od
poprzedniego punktu / od startu):

* ``speed_cms`` - prędkość na odcinku (None = domyślna prędkość trasy),
* ``hover_s`` - zawis po dojeździe (sekundy, 0 = brak),
* ``heading`` - kierunek nosa po dojeździe:

  - ``"track"`` - po torze (domyślnie),
  - ``"fixed"`` - stały kąt ``yaw_deg``,
  - ``"point"`` - nos w stronę punktu ``(look_at_x, look_at_y)``,
  - ``"start"`` - nos w stronę startu.

Zgodność wsteczna: jeśli ``speed`` jest liczbą, ma pierwszeństwo przed
``speed_cms``; ``curve`` (dawna nazwa) to ``track``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ROUTE_FORMAT = "dronesim-route"

#: dozwolone sposoby ustawienia nosa w punkcie
HEADINGS = ("track", "fixed", "point", "start")

#: domyślna wysokość pierwszego punktu (wysokość po ``takeoff``)
TAKEOFF_HEIGHT_CM = 80.0
#: domyślna prędkość trasy
DEFAULT_SPEED_CMS = 40.0
#: minimalna długość pojedynczego ruchu w trybie „prosta” (Tello: 20 cm)
MIN_MOVE_CM = 20.0
#: maksymalna długość pojedynczego ruchu ``go_xyz_speed`` (Tello: 500 cm)
MAX_MOVE_CM = 500.0
#: zakres prędkości Tello
MIN_SPEED_CMS = 10.0
MAX_SPEED_CMS = 100.0
#: zakres wysokości Tello nad ziemią
MIN_HEIGHT_CM = 10.0
MAX_HEIGHT_CM = 500.0
#: maksymalny zasięg dronemoves (``max_radius_cm`` w skrypcie)
MAX_RADIUS_CM = 500.0
#: domyślne parametry zachowania po dotarciu do trasy
DEFAULT_RETURN_HOME = False
DEFAULT_LAND = True


class RouteError(ValueError):
    """Niepoprawna trasa (komunikat dla użytkownika, po polsku)."""


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise RouteError(f"Pole '{name}' musi być liczbą.") from None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


@dataclass
class Waypoint:
    """Punkt trasy (wszystko w cm, kurs dodatni = w prawo)."""

    x: float = 0.0
    y: float = 0.0
    z: float = TAKEOFF_HEIGHT_CM
    speed_cms: Optional[float] = None
    hover_s: float = 0.0
    heading: str = "track"
    yaw_deg: float = 0.0
    look_at: Optional[Tuple[float, float]] = None
    name: str = ""

    def __post_init__(self) -> None:
        self.x = _as_float(self.x, "x")
        self.y = _as_float(self.y, "y")
        self.z = _as_float(self.z, "z")
        if self.speed_cms is not None:
            self.speed_cms = _as_float(self.speed_cms, "speed")
            if self.speed_cms <= 0:
                raise RouteError("Prędkość odcinka musi być dodatnia.")
        self.hover_s = max(0.0, _as_float(self.hover_s or 0.0, "hover_s"))
        heading = str(self.heading or "track").lower()
        if heading not in HEADINGS:
            raise RouteError(f"Nieznany kierunek nosa: {heading!r} "
                             f"(dozwolone: {', '.join(HEADINGS)}).")
        self.heading = heading
        self.yaw_deg = _as_float(self.yaw_deg or 0.0, "yaw_deg") % 360.0
        if self.look_at is not None:
            lx, ly = self.look_at
            self.look_at = (_as_float(lx, "look_at_x"), _as_float(ly, "look_at_y"))
        self.name = str(self.name or "")

    @property
    def position(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "z": round(self.z, 2),
            "heading": self.heading,
            "hover_s": round(self.hover_s, 2),
        }
        if self.speed_cms is not None:
            data["speed"] = round(self.speed_cms, 2)
        if self.heading == "fixed":
            data["yaw_deg"] = round(self.yaw_deg, 2)
        if self.heading == "point" and self.look_at is not None:
            data["look_at"] = [round(self.look_at[0], 2), round(self.look_at[1], 2)]
        if self.name:
            data["name"] = self.name
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Waypoint":
        if not isinstance(data, dict):
            raise RouteError("Punkt trasy musi być obiektem.")
        speed = data.get("speed", data.get("speed_cms"))
        heading = data.get("heading") or data.get("yaw_mode") or "track"
        if heading == "curve":
            heading = "track"
        look_at = data.get("look_at")
        if isinstance(look_at, dict):
            look_at = (look_at.get("x"), look_at.get("y"))
        elif not isinstance(look_at, (list, tuple)) or len(look_at) != 2:
            look_at = None
        return cls(
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            z=data.get("z", TAKEOFF_HEIGHT_CM),
            speed_cms=speed,
            hover_s=data.get("hover_s", data.get("hover", 0.0)) or 0.0,
            heading=str(heading),
            yaw_deg=data.get("yaw_deg", data.get("yaw", 0.0)) or 0.0,
            look_at=look_at,
            name=data.get("name", ""),
        )


@dataclass
class Route:
    """Trasa: punkty + opcje lotu."""

    points: List[Waypoint] = field(default_factory=list)
    default_speed: float = DEFAULT_SPEED_CMS
    return_home: bool = DEFAULT_RETURN_HOME
    land_at_end: bool = DEFAULT_LAND
    mode: str = "smooth"
    start_yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        self.default_speed = _as_float(self.default_speed, "default_speed")
        if self.default_speed <= 0:
            raise RouteError("Domyślna prędkość musi być dodatnia.")
        self.return_home = _as_bool(self.return_home, DEFAULT_RETURN_HOME)
        self.land_at_end = _as_bool(self.land_at_end, DEFAULT_LAND)
        self.mode = str(self.mode or "smooth").lower()
        if self.mode not in ("smooth", "simple"):
            raise RouteError("Tryb generowania musi być 'smooth' albo 'simple'.")
        self.start_yaw_deg = _as_float(self.start_yaw_deg or 0.0, "start_yaw_deg") % 360.0

    # ------------------------------------------------------------- właściwości
    def speed_for(self, index: int) -> float:
        """Prędkość odcinka do punktu ``index`` (cm/s)."""
        speed = self.points[index].speed_cms
        return self.default_speed if speed is None else speed

    def legs(self) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]:
        """Odcinki ``(start, koniec)`` w cm; start = ``(0, 0, takeoff)``."""
        previous = (0.0, 0.0, TAKEOFF_HEIGHT_CM)
        result = []
        for point in self.points:
            result.append((previous, point.position))
            previous = point.position
        return result

    def leg_lengths(self) -> List[float]:
        return [math.dist(a, b) for a, b in self.legs()]

    def waypoints(self) -> List[Tuple[float, float, float]]:
        """Punkty trasy w cm (bez startu) - dla ``pilot.path([...])``."""
        return [point.position for point in self.points]

    # -------------------------------------------------------------- zapis/odczyt
    def as_dict(self) -> Dict[str, Any]:
        return {
            "format": ROUTE_FORMAT,
            "version": 1,
            "mode": self.mode,
            "default_speed": round(self.default_speed, 2),
            "return_home": self.return_home,
            "land_at_end": self.land_at_end,
            "start_yaw_deg": round(self.start_yaw_deg, 2),
            "points": [p.as_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Route":
        if not isinstance(data, dict):
            raise RouteError("Trasa musi być obiektem.")
        if data.get("format") not in (None, ROUTE_FORMAT):
            raise RouteError(f"To nie jest trasa planera (format {data.get('format')!r}).")
        raw = data.get("points")
        if raw is None:
            raw = data.get("waypoints") or []
        if not isinstance(raw, list):
            raise RouteError("Pole 'points' musi być listą punktów.")
        if len(raw) > 300:
            raise RouteError("Trasa może mieć najwyżej 300 punktów.")
        return cls(
            points=[Waypoint.from_dict(item) for item in raw],
            default_speed=data.get("default_speed", data.get("speed", DEFAULT_SPEED_CMS)),
            return_home=data.get("return_home", DEFAULT_RETURN_HOME),
            land_at_end=data.get("land_at_end", data.get("land", DEFAULT_LAND)),
            mode=data.get("mode", "smooth"),
            start_yaw_deg=data.get("start_yaw_deg", 0.0),
        )

    def copy(self) -> "Route":
        return Route.from_dict(self.as_dict())


# ------------------------------------------------------------ blok-znacznik kodu
BLOCK_START = "# --- TRASA DRONESIM (nie usuwaj: pozwala wczytać trasę z powrotem) ---"
BLOCK_END = "# --- KONIEC TRASY DRONESIM ---"
BEGIN_MARK = "# dronesim-route:begin"
END_MARK = "# dronesim-route:end"


def route_block(route: Route, mode: str) -> str:
    """Blok komentarzy z trasą w JSON (do wczytania z powrotem do edytora)."""
    payload = route.as_dict()
    payload["mode"] = mode
    body = json.dumps(payload, ensure_ascii=True, indent=2)
    lines = [BLOCK_START, BEGIN_MARK]
    lines.extend(f"# {line}" for line in body.splitlines())
    lines.extend([END_MARK, BLOCK_END])
    return "\n".join(lines)


def load_route_from_script(source: str) -> Route:
    """Wyciągnij trasę z bloku-znacznika.

    :raises RouteError: gdy skrypt nie ma bloku albo JSON jest uszkodzony
        (komunikat jest przyjazny - użytkownik wkleił dowolny skrypt)
    """
    text = source or ""
    start = text.find(BLOCK_START)
    if start < 0:
        raise RouteError("Ten skrypt nie zawiera trasy planera - wczytaj skrypt "
                         "wygenerowany przez „Planer trasy”.")
    begin = text.find(BEGIN_MARK, start)
    finish = text.find(END_MARK, begin)
    if begin < 0 or finish < 0:
        raise RouteError("Blok trasy w skrypcie jest niekompletny (brak końca bloku).")
    lines = text[begin + len(BEGIN_MARK):finish].splitlines()
    body = "\n".join(line.strip()[1:].strip() if line.strip().startswith("#") else line
                     for line in lines)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RouteError(f"Trasa w skrypcie jest uszkodzona (JSON: {exc.msg}).") from None
    return Route.from_dict(data)


    def waypoints(self) -> List[Tuple[float, float, float]]:
        """Punkty trasy w cm (bez startu) - dla ``pilot.path([...])``."""
        return [point.position for point in self.points]

