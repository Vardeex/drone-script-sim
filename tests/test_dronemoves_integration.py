"""Testy integracyjne biblioteki dronemoves w symulatorze.

Testują kontrakt między biblioteką a symulatorem: adnotacje manewrów,
grupowanie komend RC i zaplanowaną trajektorię (``planned_trail``).
Biblioteka jest instalowana w venv (``pip install -e lib/dronemoves``).
"""

import pytest

from app import runner

SOURCE = """\
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
with Pilot(t, speed=40) as p:
    p.forward(50)
    p.circle(radius=100, direction="right")
    p.hover(1)
t.land()
"""


@pytest.fixture(scope="module")
def flight():
    result = runner.run_script(SOURCE, "dronemoves_integration.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    return result.flight


def test_maneuver_annotations_are_recorded(flight):
    labels = [e["args"][0] for e in flight.events if e["command"] == "annotate"]
    assert labels[0].startswith("start: forward 50cm")
    assert any(label.startswith("start: circle r=100") for label in labels)
    assert any(label.startswith("end: circle r=100") for label in labels)
    assert all(e["status"] == "ok" for e in flight.events if e["command"] == "annotate")


def test_rc_commands_are_grouped_by_maneuver(flight):
    grouped = {}
    for event in flight.events:
        name = event.get("maneuver")
        if name:
            grouped[name] = grouped.get(name, 0) + 1
    # setki komend RC zebrane pod nazwą manewru
    circle = next((count for name, count in grouped.items() if name.startswith("circle")), 0)
    assert circle > 100
    assert any(name.startswith("forward 50cm") for name in grouped)
    assert any(name.startswith("hover") for name in grouped)


def test_planned_trail_is_exported(flight):
    trail = flight.planned_trail
    assert len(trail) > 50
    labels = {point["label"] for point in trail}
    assert any(label.startswith("forward 50cm") for label in labels)
    assert any(label.startswith("circle r=100") for label in labels)
    # plan jest ciągły w czasie i zaczyna się w punkcie startu
    times = [point["t"] for point in trail]
    assert times == sorted(times)
    assert abs(trail[0]["x"]) < 1 and abs(trail[0]["y"]) < 1


def test_drone_actually_flew(flight):
    stats = flight.stats
    assert stats["duration_s"] > 15
    assert stats["distance_cm"] > 300


def test_planned_trail_saved_in_flight_file(flight, tmp_path):
    from app import storage

    data = storage.flight_to_dict(flight, "test-id")
    assert data["planned_trail"]
    assert data["planned_trail"][0]["label"]


# ------------------------------------------- zgodność biblioteka <-> symulator
# Każdy manewr uruchamiany osobno przez runner: końcowa pozycja z telemetrii
# symulatora musi się zgadzać z pilot.position() (tolerancja 10 cm i 5 deg).

MANEUVER_TEMPLATE = """\
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
{body}
print("PILOT", json.dumps({{"x": pilot.x, "y": pilot.y, "yaw": pilot.yaw}}))
t.land()
"""

MANEUVERS = [
    ("forward(100)", "pilot.forward(100)"),
    ("turn(90, radius=60)", "pilot.turn(90, radius=60)"),
    ("turn(-90, radius=60)", "pilot.turn(-90, radius=60)"),
    ("arc(180, radius=100)", "pilot.arc(180, radius=100)"),
    ("arc(-120, radius=80)", "pilot.arc(-120, radius=80)"),
    ("circle(60, left)", "pilot.circle(radius=60, direction='left')"),
    ("circle(60, right)", "pilot.circle(radius=60, direction='right')"),
    ("orbit(60, 1)", "pilot.orbit(radius=60, turns=1.0)"),
    ("slalom(3, 70, 40)", "pilot.slalom(gates=3, spacing=70, width=40)"),
    ("figure_eight(60)", "pilot.figure_eight(radius=60)"),
    ("spiral(50, 60, 3)", "pilot.spiral(radius=50, height=60, turns=3)"),
    ("path(3D)", "pilot.path([(80, 0, 0), (80, 60, 20), (0, 60, 40)])"),
]

#: tolerancja: 10 cm w poziomie i 5 deg kursu
POSITION_TOLERANCE_CM = 10.0
YAW_TOLERANCE_DEG = 5.0


def _pilot_state(result):
    """Odczytaj ``PILOT {...}`` wypisane przez skrypt."""
    for line in result.stdout or []:
        text = line if isinstance(line, str) else str(line.get("text", ""))
        if text.startswith("PILOT "):
            import json

            return json.loads(text[6:])
    return None


@pytest.mark.parametrize("name,body", MANEUVERS, ids=[m[0] for m in MANEUVERS])
def test_maneuver_matches_simulator(name, body):
    """Symulator wykonuje manewr tak samo jak zakłada biblioteka."""
    import math

    source = MANEUVER_TEMPLATE.format(body=body)
    result = runner.run_script(source, "maneuver.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    pilot = _pilot_state(result)
    assert pilot is not None, result.stderr

    # telemetria przed lądowaniem (land() zjeżdża do z = 0, ale XY/yaw nie zmienia)
    last = result.flight.samples[-1]
    dx = last["x"] - pilot["x"]
    dy = last["y"] - pilot["y"]
    distance = math.hypot(dx, dy)
    dyaw = abs(((last["yaw"] - pilot["yaw"]) % 360 + 540) % 360 - 180)

    assert distance <= POSITION_TOLERANCE_CM, (
        f"{name}: symulator ({last['x']:.1f}, {last['y']:.1f}) vs pilot "
        f"({pilot['x']:.1f}, {pilot['y']:.1f}) - różnica {distance:.1f} cm")
    assert dyaw <= YAW_TOLERANCE_DEG, (
        f"{name}: kurs symulatora {last['yaw']:.1f}° vs pilot {pilot['yaw']:.1f}° "
        f"- różnica {dyaw:.1f}°")
