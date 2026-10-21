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
    # przelot przez środek: 40 cm do boków, 15 cm do górnej belki (17,5 cm od
    # środka drona, bo liczy się górna powierzchnia bryły)
    assert report["stats"]["min_distance_cm"] == pytest.approx(17.5, abs=0.5)
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
    # otwór ma 90 cm, dron 10 cm - przy y = 50 dron zachodzi na ramę
    report = C.analyse_flight(straight(y=50), [], scene.as_dict())
    assert report["stats"]["gates_passed"] == 0
    assert report["stats"]["collisions"] == 1
    message = next(f["message"] for f in report["findings"] if f["level"] == "collision")
    assert "otworze" in message


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
# Scena `scenes/gate_slalom.json`: bramka 1 w (150, 0), rama 120 x 120,
# otwór 90 x 90, środek otworu na z = 80 (belki: dół 20-35, góra 125-140,
# boki 90-105 i -105..-90 cm od osi).
SLALOM_GATE = {"id": "gate-1", "kind": "gate", "name": "Bramka 1 (środek)",
               "position": [150, 0, 80], "size": [120, 5, 120],
               "opening": [90, 90], "yaw_deg": 0}


def slalom_scene() -> dict:
    return {"obstacles": [SLALOM_GATE]}


def slalom_gate() -> Obstacle:
    return Scene.from_dict(slalom_scene()).gates()[0]


def test_gate_distance_measures_to_frame_not_plane():
    """Dron 140 cm przed bramką (x = 10, z = 80) - odległość do ramy ~133 cm.

    Do najbliższej belki (dolna/górna, z = 35 / 125) jest
    139,3 cm, odejmujemy 5 cm połowy wysokości drona -> ok. 134 cm.
    (Stary błąd mierzył przenikanie płaszczyzny ramy: 140 - 5/2 = 137,5 cm
    w poziomie, a z brakiem prawidłowego złożenia pionu dawał ~2,5 cm.)
    """
    gate = slalom_gate()
    assert C._gate_distance((10.0, 0.0, 80.0), 0.0, gate) == pytest.approx(134.3, abs=3.0)


def test_gate_center_pass_distance_is_half_opening():
    """Przelot przez środek otworu: 40 cm do boków, 15 cm do górnej belki."""
    gate = slalom_gate()
    # górna powierzchnia drona (82,5) jest 17,5 cm od dolnej krawędzi górnej belki (100)
    assert C._gate_distance((150.0, 0.0, 80.0), 0.0, gate) == pytest.approx(17.5, abs=0.5)
    # obok ramy (y = 105 -> krawędź drona 100, rama kończy się na 60):
    # 40 cm w poziomie + 2,5 cm w pionie (górna powierzchnia vs. koniec ramy)
    assert C._gate_distance((150.0, 105.0, 80.0), 0.0, gate) == pytest.approx(43.7, abs=3.0)


def test_gate_plane_is_not_an_obstacle():
    """Przelot „na wylot” przez płaszczyznę ramy nie jest kolizją ani zbliżeniem."""
    samples = [
        {"t": 0.0, "x": 0.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 300.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], slalom_scene())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["gates_passed"] == 1
    assert report["stats"]["min_distance_cm"] == pytest.approx(17.5, abs=1.0)
    assert all(f["level"] != "collision" for f in report["findings"])


def test_slalom_hover_140cm_in_front_reports_140cm():
    """Lot w miejscu 140 cm przed bramką 1 (jak po move_left(200)) -> ~134 cm."""
    samples = [{"t": i * 0.1, "x": 10.0, "y": 0.0, "z": 80.0, "yaw": 0.0}
               for i in range(11)]
    report = C.analyse_flight(samples, [], slalom_scene())
    stats = report["stats"]
    assert stats["collisions"] == 0
    assert stats["warnings"] == 0
    assert stats["min_distance_cm"] == pytest.approx(134.3, abs=3.0)
    assert stats["min_distance_obstacle"] == "Bramka 1 (środek)"


def test_slalom_center_pass_reports_frame_clearance():
    """Lot od startu przez środek otworu bramki 1 - odstęp od ramy 15 cm.

    Lewą/prawą belkę ramy dzieli od osi lotu 40 cm, górną belkę 15 cm, więc
    minimalny odstęp to 15 cm - (w starym kodzie 2,5 cm „od płaszczyzny”).
    """
    samples = [
        {"t": 0.0, "x": 0.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 200.0, "y": 0.0, "z": 80.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], slalom_scene())
    stats = report["stats"]
    assert stats["gates_passed"] == 1
    assert stats["collisions"] == 0
    assert stats["min_distance_cm"] == pytest.approx(15.0, abs=3.0)
    warnings = [f for f in report["findings"] if f["level"] == "warning"]
    # ostrzeżenia pokazują rzeczywisty odstęp od belek ramy (15 cm)
    assert warnings and all(f["distance_cm"] >= 14.0 for f in warnings)


def test_gate_passer_by_40cm_has_no_collision():
    """Lot obok bramki (40 cm od ramy) nie jest kolizją ani zbliżeniem."""
    samples = [
        {"t": 0.0, "x": 0.0, "y": 105.0, "z": 80.0, "yaw": 0.0},
        {"t": 1.0, "x": 300.0, "y": 105.0, "z": 80.0, "yaw": 0.0},
    ]
    report = C.analyse_flight(samples, [], slalom_scene())
    assert report["stats"]["collisions"] == 0
    assert report["stats"]["warnings"] == 0
    assert report["stats"]["gates_passed"] == 0
    # bok ramy 40 cm od osi lotu, licząc od krawędzi drona (5 cm) -> ~45 cm
    assert report["stats"]["min_distance_cm"] == pytest.approx(45.0, abs=3.0)

