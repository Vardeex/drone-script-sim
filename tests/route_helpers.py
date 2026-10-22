"""Pomocnicze funkcje testów planera trasy.

Wszystkie oczekiwane wartości w testach planera liczymy **z geometrii**
(komentarz przy każdej asercji), a nie z wyniku programu.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

Point = Tuple[float, float, float]


def run_script(client: Any, source: str, name: str = "trasa.py",
               options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Uruchom skrypt w symulatorze (``POST /api/run``) i zwróć zapisany lot."""
    started = client.post("/api/run", json={
        "source": source, "script_name": name,
        "options": options or {},
    })
    assert started.status_code == 200, started.text
    run_id = started.json()["id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        data = client.get(f"/api/run/live/{run_id}").json()
        if data["status"] != "running":
            assert data["status"] == "done", data.get("error")
            return data["flight"]
        time.sleep(0.05)
    raise AssertionError("Skrypt nie zakończył się w czasie.")


def points_near(samples: Sequence[Dict[str, Any]],
                point: Point) -> List[Dict[str, Any]]:
    """Próbki telemetrii posortowane po odległości od punktu (rosnąco)."""
    return sorted(samples, key=lambda s: math.dist((s["x"], s["y"], s["z"]), point))


def min_distance(samples: Sequence[Dict[str, Any]], point: Point) -> float:
    """Najmniejsza odległość toru lotu od punktu (cm)."""
    return min(math.dist((s["x"], s["y"], s["z"]), point) for s in samples)


def visit_times(samples: Sequence[Dict[str, Any]], points: Sequence[Point],
                limit_cm: float = 30.0) -> List[float]:
    """Czasy pierwszego zbliżenia do każdego punktu (``limit_cm``) w kolejności trasy.

    Kolejność jest wymuszona: punkt ``i`` szukamy dopiero od chwili odwiedzenia
    punktu ``i-1`` (trasa ma przechodzić przez punkty po kolei). Ostatni punkt
    trasy może być blisko punktu startu, więc bez tego sprawdzenie „czy w ogóle
    był blisko” nic nie mówi o kolejności.
    """
    times: List[float] = []
    since = -math.inf
    for point in points:
        near = [s["t"] for s in samples
                if s["t"] >= since - 1e-6
                and math.dist((s["x"], s["y"], s["z"]), point) <= limit_cm]
        reached = min(near) if near else math.inf
        if reached < math.inf:
            since = reached
        times.append(reached)
    return times


def is_monotonic(values: Sequence[float]) -> bool:
    """Czy wartości są niemalejące (kolejność odwiedzania punktów)."""
    return all(b >= a - 0.4 for a, b in zip(values, values[1:]))


def yaw_error(actual: float, target: float) -> float:
    """Odchylenie kursu (stopnie, różnica okrężna 0-180)."""
    return abs((actual - target + 180.0) % 360.0 - 180.0)


def sample_at(samples: Sequence[Dict[str, Any]], t: float) -> Dict[str, Any]:
    """Próbka telemetrii najbliższa czasowi ``t``."""
    return min(samples, key=lambda s: abs(s["t"] - t))
