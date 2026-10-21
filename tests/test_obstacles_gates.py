"""Testy geometrii bramki (przelot, zawadzenie, ominięcie)."""

from __future__ import annotations

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
    assert report["findings"][0]["level"] == "gate"


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
    assert "otworze" in report["findings"][0]["message"]


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
