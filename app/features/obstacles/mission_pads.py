"""Wykrywanie mat (Mission Pads) Tello EDU — geometria i założenia.

Prawdziwy Tello EDU wykrywa maty **kamerą dolną**; w dokumentacji Tello SDK 2.0
nie ma podanego dokładnego zasięgu, więc przyjmujemy wartości mieszczące się
w tym, co podają materiały DJI i praktyka użytkowników (pole widzenia kamery
dolnej + rozmiar maty 30 × 30 cm):

============================  ==========  ====================================
parametr                      wartość     źródło
============================  ==========  ====================================
zasięg poziomy od środka      ≤ 30 cm     mata ma 30 × 30 cm; kamera dolna ma
                                          szersze pole widzenia, więc przy
                                          krawędzi maty kod jest jeszcze czytany
wysokość nad matą             30–120 cm   poniżej 30 cm obraz jest rozmyty,
                                          powyżej ~1,2 m kod jest za mały
rozpoznawanie kodu maty       do 1 m      (ta sama informacja co wysokość)
częstotliwość ramek           10 Hz       SDK 2.0: przy obu kierunkach 10 Hz,
                                          20 Hz przy jednym (``mdirection``)
============================  ==========  ====================================

**To są założenia modelu, nie pomiary.** Zmiana wartości w jednym miejscu
(:data:`DETECTION_RADIUS_CM`, :data:`DETECTION_MIN_HEIGHT_CM`,
:data:`DETECTION_MAX_HEIGHT_CM`) zmienia zachowanie symulatora i testów.

Układ współrzędnych maty (Tello SDK 2.0, ``go x y z speed mID``): ``x`` = przód
maty, ``y`` = lewo maty, ``z`` = w górę od maty, początek w środku maty.
Obrót maty ``yaw_deg`` (dodatni = w prawo, jak wszędzie w projekcie) obraca ten
układ w układzie świata.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .model import PAD_IDS

Vec3 = Tuple[float, float, float]

__all__ = [
    "DETECTION_HZ", "DETECTION_MAX_HEIGHT_CM", "DETECTION_MIN_HEIGHT_CM",
    "DETECTION_RADIUS_CM", "PAD_IDS", "PadError", "find_pad", "pad_offset",
    "pad_target_world", "scene_pads", "visible_pad",
]

#: maksymalna odległość pozioma od środka maty, przy której mata jest widziana [cm]
DETECTION_RADIUS_CM = 30.0
#: dolna granica wysokości nad matą [cm] - niżej obraz kamery jest rozmyty
DETECTION_MIN_HEIGHT_CM = 30.0
#: górna granica wysokości nad matą [cm] - wyżej kod jest za mały
DETECTION_MAX_HEIGHT_CM = 120.0
#: częstotliwość wykrywania (SDK 2.0: 10 Hz przy dwóch kierunkach) [Hz]
DETECTION_HZ = 10.0


class PadError(ValueError):
    """Mata o danym numerze/kierunku nie jest dostępna (jak odpowiedź ``error``)."""


def visible_pad(position: Sequence[float], pads: Sequence[Dict[str, Any]],
                direction: int = 0) -> Optional[Dict[str, Any]]:
    """Mata widziana przez kamerę dolną w danym położeniu drona.

    :param position: pozycja drona w układzie świata ``(x, y, z)`` [cm]
    :param pads: maty sceny (słowniki ``Obstacle.as_dict()`` z ``kind == "mission_pad"``)
    :param direction: kierunek wykrywania (0 = dół, 1 = przód, 2 = oba);
        1 i 2 wymagają kamery skierowanej do przodu, której model nie ma,
        więc wykrywanie działa tylko w dół (jak ``direction = 0``)
    :return: słownik maty albo ``None``, gdy żadna nie jest widziana

    Przy kilku matach w zasięgu wybierana jest **najbliższa środkiem**
    (tak zachowuje się kamera: kod w centrum kadru jest czytany najlepiej).
    """
    if direction not in (0, 1, 2):
        raise PadError(f"Kierunek wykrywania musi być 0, 1 lub 2 (jest {direction}).")
    x, y, z = (float(v) for v in position[:3])
    best: Optional[Dict[str, Any]] = None
    best_distance = float("inf")
    for pad in pads:
        center = pad.get("position") or (0.0, 0.0, 0.0)
        height = z - float(center[2])
        if not (DETECTION_MIN_HEIGHT_CM <= height <= DETECTION_MAX_HEIGHT_CM):
            continue
        distance = math.hypot(x - float(center[0]), y - float(center[1]))
        if distance > DETECTION_RADIUS_CM:
            continue
        if distance < best_distance:
            best, best_distance = pad, distance
    return best


def pad_offset(position: Sequence[float], yaw_world_deg: float,
               pad: Dict[str, Any]) -> Vec3:
    """Pozycja drona względem maty w układzie maty ``(x przód, y lewo, z góra)``.

    :param position: pozycja drona w układzie świata [cm]
    :param yaw_world_deg: kurs drona (konwencja projektu: dodatni = w prawo)
    :param pad: słownik maty (``position``, ``yaw_deg``)
    """
    center = pad.get("position") or (0.0, 0.0, 0.0)
    dx = float(position[0]) - float(center[0])
    dy = float(position[1]) - float(center[1])
    dz = float(position[2]) - float(center[2])
    # obrót o -yaw maty: mata obrócona w prawo o kąt θ ma oś X świata obróconą
    # o -θ w układzie „x przód, y lewo” (ta sama konwencja co w pilot.position())
    angle = -math.radians(float(pad.get("yaw_deg") or 0.0))
    px = dx * math.cos(angle) - dy * math.sin(angle)
    py = dx * math.sin(angle) + dy * math.cos(angle)
    return (px, py, dz)


def pad_target_world(pad: Dict[str, Any], target: Sequence[float]) -> Vec3:
    """Punkt ``target`` w układzie maty -> współrzędne świata."""
    center = pad.get("position") or (0.0, 0.0, 0.0)
    angle = -math.radians(float(pad.get("yaw_deg") or 0.0))
    tx, ty, tz = (float(v) for v in target[:3])
    # odwrotność obrotu z :func:`pad_offset`
    wx = tx * math.cos(angle) + ty * math.sin(angle)
    wy = -tx * math.sin(angle) + ty * math.cos(angle)
    return (float(center[0]) + wx, float(center[1]) + wy, float(center[2]) + tz)


def find_pad(pads: Sequence[Dict[str, Any]], pad_id: int) -> Optional[Dict[str, Any]]:
    """Mata o numerze ``pad_id`` (None, gdy nie ma jej w scenie)."""
    for pad in pads:
        if int(pad.get("pad_id") or 0) == int(pad_id):
            return pad
    return None


def scene_pads(scene: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lista mat ze sceny (``None`` = brak sceny = brak mat)."""
    if not scene:
        return []
    return [o for o in (scene.get("obstacles") or [])
            if str(o.get("kind") or "") == "mission_pad"]
