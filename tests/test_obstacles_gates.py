"""Testy geometrii bramki (przelot, zawadzenie, ominięcie)."""

from __future__ import annotations

import pytest

from app.features.obstacles import collisions as C
from app.features.obstacles.model import Obstacle, Scene


def gate(x: float = 150.0, y: float = 0.0, z: float = 80.0, yaw: float = 0.0) -> Obstacle:
    return Obstacle(kind="gate", name="bramka", position=(x, y, z),
                    size=(120, 5, 120), opening=(90, 90), yaw_deg=yaw)


def straight(y: float = 0.0, z: float = 80.0, start: float = 0.0, end: float = 300.0,
             speed: float = 300.0, dt: float = 0.05):
    """Prosty lot po osi X (przelot w poprzek ramy yaw=0)."""
    samples = []
    t = 0.0
    x = start
    while x <= end + 1e-9:
        samples.append({"t": round(t, 4), "x": x, "y": y, "z": z, "yaw": 0.0})
        x += speed * dt
        t += dt
    return samples


def test_gate_through_center_is_passed():
    scene = Scene(obstacles=[gate()])
    report = C.analyse_flight(straight(), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 1
    assert report["stats"]["collisions"] == 0
    # przelot przez środek otworu: luz = min(45 - 0, 45 - 0) = 40 cm
    assert report["stats"]["min_distance_cm"] == pytest.approx(40.0, abs=0.5)
    entry = next(f for f in report["findings"] if f["level"] == "gate")
    assert "bramka" in entry["message"]


def test_gate_pass_geometry_center_and_edges():
    """Otwór 90 cm, dron 10 cm, tolerancja 2 cm -> czysto do y = 38 cm, kolizja od 39 cm."""
    g = gate()
    assert C._gate_pass_at(0.0, g, 1.0, 0.0) == "clean"
    assert C._gate_pass_at(33.0, g, 1.0, 0.0) == "clean"
    assert C._gate_pass_at(38.0, g, 1.0, 0.0) == "clean"      # 38 + 5 = 43 = 45 - 2
    assert C._gate_pass_at(39.0, g, 1.0, 0.0) == "touch"
    assert C._gate_pass_at(45.0, g, 1.0, 0.0) == "touch"


def test_gate_pass_geometry_offset_from_center():
    """Bramka przesunięta w bok: liczy się odległość od JEJ środka, nie od x = 0."""
    g = gate(y=45.0)
    assert abs(g.to_local((150.0, 45.0))[1]) < 1e-9
    assert C._gate_pass_at(g.to_local((150.0, 45.0))[1], g, 1.0, 0.0) == "clean"
    assert C._gate_pass_at(g.to_local((150.0, 12.0))[1], g, 1.0, 0.0) == "clean"
    assert C._gate_pass_at(g.to_local((150.0, 0.0))[1], g, 1.0, 0.0) == "touch"


def test_gate_offset_flight_through_opening_is_passed():
    scene = Scene(obstacles=[gate(y=45.0)])   # analiza porównuje y w skali globalnej
    report = C.analyse_flight(straight(y=45.0), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 1, report["findings"]


def test_gate_too_far_side_hits_frame():
    scene = Scene(obstacles=[gate()])
    # otwór ma 90 cm, dron 10 cm - przy y = 50 dron zachodzi na ramę;
    # to jedno zdarzenie (wejście w belkę), nie dwa wpisy
    report = C.analyse_flight(straight(y=50), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0
    assert report["stats"]["collisions"] == 1, report["findings"]


def test_gate_missed_entirely_is_not_counted():
    scene = Scene(obstacles=[gate()])
    report = C.analyse_flight(straight(y=150), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0
    assert report["stats"]["collisions"] == 0


def test_gate_over_the_top_is_not_counted():
    scene = Scene(obstacles=[gate()])
    report = C.analyse_flight(straight(z=200), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0


def test_gate_side_step_in_plane_is_not_a_pass():
    """Zatrzymanie w płaszczyźnie ramy i zjazd bokiem to nie przelot."""
    scene = Scene(obstacles=[gate()])
    samples = [
        {"t": 0.0, "x": 0.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 150.0, "y": 0.0, "z": 80.0, "yaw": 0.0},   # dokładnie w ramie
        {"t": 2.0, "x": 150.0, "y": 150.0, "z": 80.0, "yaw": 0.0},  # zjazd bokiem
    ]
    report = C.analyse_flight(samples, [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0


def test_gate_rotated_90_degrees_requires_flight_along_y():
    """Bramka obrócona o 90° jest prostopadła do osi Y - przelot po X ją mija."""
    scene = Scene(obstacles=[gate(yaw=90)])
    report = C.analyse_flight(straight(), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0

# --------------------------------------------------- odległość od ramy bramki
# Scena `scenes/gate_slalom.json`, bramka 1:
#   środek (150, 0, 80), rama 120 x 120 (x: 147,5-152,5, z: 20-140),
#   otwór 90 x 90 (y: -45..45, z: 35-125), dron 10 x 10 x 5 cm.
SLALOM_GATE = {"id": "gate-1", "kind": "gate", "name": "Bramka 1 (środek)",
               "position": [150, 0, 80], "size": [120, 5, 120],
               "opening": [90, 90], "yaw_deg": 0}


def slalom_scene() -> dict:
    return {"obstacles": [SLALOM_GATE]}


def slalom_gate() -> Obstacle:
    return Scene.from_dict(slalom_scene()).gates()[0]


def horiz_z(z: float) -> list:
    """Trasa w osi bramki (y = 0) na wysokości ``z``, od x = 0 do x = 250."""
    return [
        {"t": 0.0, "x": 0.0, "y": 0.0, "z": z, "yaw": 0.0},
        {"t": 5.0, "x": 250.0, "y": 0.0, "z": z, "yaw": 0.0},
    ]


def test_gate_center_distance_is_half_opening():
    """Dron w środku otworu: luz = min(45 - 0, 45 - 0) = 40 cm.

    Otwór 90 x 90 -> półotwór 45 cm. Dron w (150, 0, 80) ma środek ościeżnicy
    45 cm od każdej belki; promień drona w płaszczyźnie ramy to 5 cm, więc
    luz mierzony od środka do krawędzi otworu to 40 cm (od boku drona).
    """
    gate = slalom_gate()
    assert C._gate_distance((150.0, 0.0, 80.0), 0.0, gate) == pytest.approx(40.0, abs=0.5)


def test_gate_top_bar_center_is_collision():
    """(150, 0, 135) to środek górnej belki (z: 125-140) -> 0 cm."""
    gate = slalom_gate()
    assert C._gate_distance((150.0, 0.0, 135.0), 0.0, gate) == pytest.approx(0.0, abs=0.1)


def test_gate_bottom_bar_is_collision():
    """(150, 0, 30) leży w dolnej belce (z: 20-35) -> 0 cm."""
    gate = slalom_gate()
    assert C._gate_distance((150.0, 0.0, 30.0), 0.0, gate) == pytest.approx(0.0, abs=0.1)


def test_gate_side_bar_is_collision():
    """(150, 55, 80): otwór kończy się na y = 45, rama na y = 60 -> 0 cm.

    Dron 10 cm szerokości sięga od y = 50 do 60, czyli w belkę boczną.
    """
    gate = slalom_gate()
    assert C._gate_distance((150.0, 55.0, 80.0), 0.0, gate) == pytest.approx(0.0, abs=0.1)


def test_gate_above_frame_distance():
    """(150, 0, 150) nad ramą: 150 - 2,5 (pół wysokości drona) - 140 (góra ramy) = 7,5 cm."""
    gate = slalom_gate()
    assert C._gate_distance((150.0, 0.0, 150.0), 0.0, gate) == pytest.approx(7.5, abs=0.2)


def test_gate_distance_measures_to_frame_not_plane():
    """140 cm przed bramką (x = 10, z = 80): odległość do ramy, nie do płaszczyzny.

    Najbliższy punkt ramy to górna belka: krawędź drona (x = 15) i górna
    powierzchnia (z = 82,5) kontra wierzchołek ramy (x = 147,5, z = 125):
    sqrt(132,5^2 + 42,5^2) = 139,2 cm. Środek drona jest 140 cm od płaszczyzny.
    """
    gate = slalom_gate()
    assert C._gate_distance((10.0, 0.0, 80.0), 0.0, gate) == pytest.approx(139.2, abs=3.0)


def test_gate_plane_is_not_an_obstacle():
    """Przelot „na wylot” przez otwór: 0 kolizji, 0 ostrzeżeń, luz 40 cm."""
    report = C.analyse_flight(horiz_z(80.0), [], slalom_scene())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["warnings"] == 0
    assert report["stats"]["gates_passed"] == 1
    assert report["stats"]["min_distance_cm"] == pytest.approx(40.0, abs=1.0)
    assert all(f["level"] == "gate" for f in report["findings"])


def test_slalom_hover_140cm_in_front_reports_140cm():
    """Lot w miejscu 140 cm przed bramką (x = 10, z = 80) -> 139,2 cm (jak wyżej)."""
    samples = [{"t": i * 0.1, "x": 10.0, "y": 0.0, "z": 80.0, "yaw": 0.0}
               for i in range(11)]
    report = C.analyse_flight(samples, [], slalom_scene())
    stats = report["stats"]
    assert stats["collisions"] == 0
    assert stats["warnings"] == 0
    assert stats["min_distance_cm"] == pytest.approx(139.2, abs=3.0)
    assert stats["min_distance_obstacle"] == "Bramka 1 (środek)"


def test_slalom_center_pass_reports_frame_clearance():
    """Przelot środkiem otworu: luz 40 cm, bez fałszywych ostrzeżeń."""
    report = C.analyse_flight(horiz_z(80.0), [], slalom_scene())
    stats = report["stats"]
    assert stats["gates_passed"] == 1
    assert stats["collisions"] == 0
    assert stats["warnings"] == 0
    assert stats["min_distance_cm"] == pytest.approx(40.0, abs=3.0)


def test_flight_through_top_bar_is_collision():
    """Lot takeoff (80) + move_up(55) -> z = 135 + move_forward: w górną belkę.

    z = 135 leży w belce (125-140), więc trasa musi dać kolizję z bramką 1.
    """
    samples = [
        {"t": 0.0, "x": 0.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 0.0, "y": 0.0, "z": 135.0, "yaw": 0.0},
        {"t": 6.0, "x": 200.0, "y": 0.0, "z": 135.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], slalom_scene())
    stats = report["stats"]
    assert stats["collisions"] == 1, report["findings"]
    assert stats["min_distance_cm"] == pytest.approx(0.0, abs=1e-6)
    hit = next(f for f in report["findings"] if f["level"] == "collision")
    assert hit["obstacle_name"] == "Bramka 1 (środek)"
    assert hit["distance_cm"] == 0.0


def test_flight_above_frame_only_warns():
    """Lot 10 cm nad ramą nie dotyka jej: 150 - 2,5 - 140 = 7,5 cm -> ostrzeżenie."""
    report = C.analyse_flight(horiz_z(150.0), [], slalom_scene())
    stats = report["stats"]
    assert stats["collisions"] == 0
    assert stats["warnings"] >= 1
    assert stats["min_distance_cm"] == pytest.approx(7.5, abs=0.5)


def test_gate_passer_by_40cm_has_no_collision():
    """Lot obok ramy (y = 105): krawędź drona 100, rama kończy się na 60 -> 40 cm."""
    samples = [
        {"t": 0.0, "x": 0.0, "y": 105.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 300.0, "y": 105.0, "z": 80.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], slalom_scene())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["warnings"] == 0
    assert report["stats"]["gates_passed"] == 0
    assert report["stats"]["min_distance_cm"] == pytest.approx(40.0, abs=1.0)

