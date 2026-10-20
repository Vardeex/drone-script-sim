"""Testy silnika symulacji: kinematyka, yaw, telemetria, bateria."""

from __future__ import annotations

import math

import pytest

from app.sim import core, physics


def _square_script_events(sim: core.Simulation) -> None:
    """Kwadrat 100 cm z obrotami CW 90 deg - ręcznie przez API silnika."""
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    for _ in range(4):
        ev, _, _ = sim.begin("move_forward", [100])
        sim.require_airborne("move_forward")
        sim.move_relative("move_forward", [100], 100, 0, 0, 50, ev)
        ev, _, _ = sim.begin("rotate_clockwise", [90])
        sim.rotate("rotate_clockwise", [90], -90, ev)
    ev, _, _ = sim.begin("land", [])
    sim.land(ev)


def test_square_final_position_within_tolerance():
    sim = core.Simulation()
    _square_script_events(sim)
    # tolerancja 1 cm na osie i pozycja na ziemi
    pos = sim.position
    assert pos[2] == pytest.approx(0.0, abs=1e-6)
    assert pos[0] == pytest.approx(0.0, abs=1.0)
    assert pos[1] == pytest.approx(0.0, abs=1.0)
    assert sim.yaw % 360 == pytest.approx(0.0, abs=1e-6)


def test_square_distance_and_yaw_progression():
    sim = core.Simulation()
    _square_script_events(sim)
    moved = sum(e.duration for e in sim.recorder.events if e.command == "move_forward")
    assert moved == pytest.approx(4 * 100 / 50, rel=1e-6)  # 8 s
    # dystans = kwadrat 400 cm + wznoszenie 80 cm + lądowanie 80 cm
    assert sim.distance == pytest.approx(560.0, rel=1e-6)
    assert sim.max_height == pytest.approx(80.0, abs=1e-6)


@pytest.mark.parametrize(
    "yaw_deg,expected",
    [(0, (100, 0)), (90, (0, 100)), (180, (-100, 0)), (-90, (0, -100)), (45, (70.71, 70.71))],
)
def test_relative_move_respects_yaw(yaw_deg, expected):
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    sim.yaw = yaw_deg
    ev, _, _ = sim.begin("move_forward", [100])
    sim.move_relative("move_forward", [100], 100, 0, 0, 50, ev)
    assert sim.position[0] == pytest.approx(expected[0], abs=0.05)
    assert sim.position[1] == pytest.approx(expected[1], abs=0.05)
    assert sim.position[2] == pytest.approx(80.0, abs=1e-6)


def test_left_move_is_positive_y():
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    ev, _, _ = sim.begin("move_left", [50])
    sim.move_relative("move_left", [50], 0, 50, 0, 50, ev)
    assert sim.position[0] == pytest.approx(0.0, abs=1e-6)
    assert sim.position[1] == pytest.approx(50.0, abs=1e-6)


def test_takeoff_height_default():
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    assert sim.state == core.STATE_AIRBORNE
    assert sim.position[2] == pytest.approx(80.0, abs=1e-6)
    assert sim.now == pytest.approx(80 / 50, abs=1e-6)


def test_telemetry_sampled_every_50ms():
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)  # 1.6 s
    times = [s.t for s in sim.recorder.samples]
    steps = [b - a for a, b in zip(times, times[1:])]
    assert steps, "brak próbek telemetrii"
    assert all(step <= 0.05 + 1e-9 for step in steps)
    assert any(abs(t / 0.05 - round(t / 0.05)) < 1e-6 for t in times)
    assert len(times) >= 30


def test_battery_drops_in_flight_only_faster():
    idle = core.Simulation()
    idle.advance(10.0)
    flying = core.Simulation()
    ev, _, _ = flying.begin("takeoff", [])
    flying.takeoff(ev)
    before = flying.battery
    flying.advance(10.0)
    assert flying.battery < before
    assert (idle.battery - flying.battery) > 0.1


def test_linear_move_duration_and_ramp():
    line = physics.LinearMove(start=(0, 0, 0), end=(100, 0, 0), speed=50)
    assert line.duration() == pytest.approx(2.0)
    assert line.position_at(1.0) == pytest.approx((50, 0, 0))
    ramp = physics.LinearMove(start=(0, 0, 0), end=(100, 0, 0), speed=50, accel=True,
                              accel_value=100)
    duration = ramp.duration()
    assert 2.0 < duration < 2.6  # rampa wydłuża ruch
    assert ramp.speed_at(0.0) == pytest.approx(0.0)
    assert ramp.speed_at(duration / 2) == pytest.approx(50.0, abs=1e-6)
    assert ramp.position_at(duration)[0] == pytest.approx(100.0, abs=1e-6)


def test_curve_end_position():
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    ev, _, _ = sim.begin("curve_xyz_speed", [50, 50, 0, 100, 0, 0, 50])
    sim.move_relative("curve_xyz_speed", [50, 50, 0, 100, 0, 0, 50], 100, 0, 0, 50, ev,
                      curve_control=(50, 50, 0))
    assert sim.position[0] == pytest.approx(100.0, abs=1e-6)
    assert sim.position[1] == pytest.approx(0.0, abs=1e-6)
    # łuk musi odchylić się od prostej (punkt kontrolny po lewej)
    xs = [p[1] for p in sim.recorder.spans[-1].motion.move.polyline]
    assert max(xs) > 20.0


def test_move_before_takeoff_raises():
    sim = core.Simulation()
    with pytest.raises(core.SimulationError):
        sim.require_airborne("move_forward")


def test_export_flight_data_structure():
    sim = core.Simulation()
    _square_script_events(sim)
    data = sim.to_flight_data()
    assert data.samples and data.events and data.segments
    for key in ("t", "x", "y", "z", "yaw", "vx", "vy", "vz", "battery", "state"):
        assert key in data.samples[0]
    for key in ("t", "command", "args", "status", "warning"):
        assert key in data.events[0]
    assert data.stats["distance_cm"] > 0
