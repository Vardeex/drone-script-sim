"""Testy wykrywania kolizji i zbliżeń (funkcja ``obstacles``)."""

from __future__ import annotations

from app.features.obstacles import collisions as C
from app.features.obstacles.model import Obstacle, Scene


def wall(x: float = 100.0, yaw: float = 0.0, thickness: float = 10.0,
         length: float = 400.0) -> Obstacle:
    """Cienka ściana w poprzek osi X (grubość wzdłuż X) na wysokości 80 cm."""
    return Obstacle(kind="box", name="ściana", position=(x, 0, 200),
                    size=(thickness, length, 400), yaw_deg=yaw)


def samples_along(points, step: float = 50.0, speed: float = 100.0):
    """Próbki wzdłuż łamanej z krokiem ``step`` cm (yaw = 0)."""
    result = []
    t = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:]):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) ** 0.5
        count = max(1, int(round(length / step)))
        for i in range(count):
            frac = i / count
            result.append({"t": round(t, 4), "x": x0 + (x1 - x0) * frac,
                           "y": y0 + (y1 - y0) * frac, "z": z0 + (z1 - z0) * frac,
                           "yaw": 0.0})
            t += (length / count) / speed
    last = points[-1]
    result.append({"t": round(t, 4), "x": float(last[0]), "y": float(last[1]),
                   "z": float(last[2]), "yaw": 0.0})
    return result


def test_collision_through_wall():
    scene = Scene(obstacles=[wall()])
    report = C.analyse_flight(samples_along([(0, 0, 80), (200, 0, 80)]), [], scene.as_dict())
    assert report["stats"]["collisions"] == 1
    levels = [f["level"] for f in report["findings"]]
    assert levels[0] == "warning" and "collision" in levels    # najpierw ostrzeżenie
    collision = next(f for f in report["findings"] if f["level"] == "collision")
    assert "ściana" in collision["message"]


def test_fast_flight_through_thin_wall_is_detected():
    """Próbki co 100 cm (0,05 s) przeskakują ścianę - interpolacja musi ją złapać."""
    scene = Scene(obstacles=[wall(thickness=5.0)])
    samples = [
        {"t": 0.0, "x": 60.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
        {"t": 0.05, "x": 160.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], scene.as_dict())
    assert report["stats"]["collisions"] == 1


def test_pass_beside_wall_without_warning():
    scene = Scene(obstacles=[wall()])
    # ściana kończy się na y = 200; dron leci na y = 260 (60 cm zapasu)
    report = C.analyse_flight(samples_along([(0, 260, 80), (200, 260, 80)]), [],
                              scene.as_dict())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["warnings"] == 0
    assert report["stats"]["min_distance_cm"] > 20


def test_approach_within_margin_is_warning():
    scene = Scene(obstacles=[wall()])
    # ściana kończy się na y = 200; dron (10 cm szerokości) leci na y = 235:
    # krawędź drona 230, czyli 30 cm od ściany - poza kolizją, w marginesie
    report = C.analyse_flight(samples_along([(0, 235, 80), (200, 235, 80)]), [],
                              scene.as_dict())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["warnings"] >= 1
    assert report["findings"][0]["level"] == "warning"
