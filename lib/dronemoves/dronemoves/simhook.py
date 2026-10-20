"""Zapis planu manewrów dla symulatora (tylko w środowisku symulatora).

Biblioteka **nie importuje niczego** z symulatora: wykrywa go wyłącznie po tym,
że ``djitellopy`` zostało zaimportowane z katalogu symulatora (mock), i wtedy
zapisuje plan do ``dronemoves_plan.json`` w katalogu roboczym skryptu.
Na prawdziwym dronie ten plik nigdy nie powstaje.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, List, Tuple

__all__ = ["PLAN_FILENAME", "is_simulator", "record_preview"]

#: nazwa pliku planu czytanego przez symulator (z katalogu roboczego skryptu)
PLAN_FILENAME = "dronemoves_plan.json"

#: typy drona, dla których zapisujemy plan (kolejność ma znaczenie)
_PLAN_ENTRY: List[Tuple[Any, Any]] = []
_MAX_POINTS = 4000


def is_simulator(drone: Any = None) -> bool:
    """Czy działamy w symulatorze (mock ``djitellopy``)?

    Sprawdza, że moduł ``djitellopy`` pochodzi z katalogu symulatora
    (``app/adapters/tello/djitellopy``). Nie importuje modułów symulatora.
    """
    module = sys.modules.get("djitellopy")
    if module is None:
        return False
    origin = str(getattr(module, "__file__", "") or "").replace("\\", "/").lower()
    return "app/adapters/tello/djitellopy" in origin


def _plan_payload(entries: List[Tuple[dict, float, str]]) -> dict:
    return {"format": "dronemoves-plan", "version": 1, "points": [
        {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
         "t": round(t, 3), "label": label}
        for (x, y, z), t, label in entries
    ]}


def record_preview(drone: Any, entries: List[Tuple[dict, float, str]]) -> None:
    """Dopisz zaplanowane punkty (w układzie lotu) do planu symulatora.

    Każde wywołanie dokłada kolejny manewr; czasy są już liczone w układzie lotu,
    więc w pliku jest cała trasa (kolejne manewry, nie ich nadpisanie).

    :param drone: obiekt drona (używany tylko do rozpoznania symulatora)
    :param entries: lista ``((x, y, z) [cm], t [s], label)``
    """
    if not entries or not is_simulator(drone):
        return
    path = Path.cwd() / PLAN_FILENAME
    points: List[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("points"), list):
                points = [p for p in existing["points"] if isinstance(p, dict)]
        except (OSError, ValueError):
            points = []
    points.extend(_plan_payload(entries)["points"])
    payload = {"format": "dronemoves-plan", "version": 1, "points": points[-_MAX_POINTS:]}
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # zapis planu jest opcjonalny - błąd nie może przerwać lotu
        try:
            tmp.unlink()
        except OSError:
            pass
