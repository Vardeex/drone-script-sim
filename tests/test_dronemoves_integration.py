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
