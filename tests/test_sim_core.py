"""Testy silnika symulacji: kinematyka, yaw, telemetria, bateria."""

from __future__ import annotations

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
        sim.rotation("rotate_clockwise", [90], -90, ev)
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
    # dystans = droga pozioma kwadratu (wznoszenie i lądowanie nie są liczone)
    assert sim.distance == pytest.approx(400.0, rel=1e-6)
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


def test_rotation_duration_and_yaw():
    """Obrót: 90°/s + minimum 100 ms (krótkie obroty widoczne na osi czasu)."""
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    before = sim.now
    ev, _, _ = sim.begin("rotate_counter_clockwise", [90])
    sim.rotation("rotate_counter_clockwise", [90], 90, ev)
    assert sim.now - before == pytest.approx(1.0, abs=1e-9)
    assert sim.yaw == pytest.approx(90.0)
    before = sim.now
    ev, _, _ = sim.begin("rotate_clockwise", [1])
    sim.rotation("rotate_clockwise", [1], -1, ev)
    assert sim.now - before == pytest.approx(0.1, abs=1e-9)
    assert sim.yaw % 360 == pytest.approx(89.0)


def test_move_before_takeoff_raises():
    sim = core.Simulation()
    with pytest.raises(core.SimulationError):
        sim.require_airborne("move_forward")


def test_long_sleep_does_not_explode_telemetry():
    """Długie ``sleep`` w pętli nie może generować setek tysięcy próbek."""
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    start = sim.now
    before = len(sim.recorder.samples)
    sim.advance(600.0)  # 10 min bezczynności (symulacja liczy od końca takeoffu)
    assert sim.now == pytest.approx(start + 600.0)
    added = len(sim.recorder.samples) - before
    # przy 50 ms byłoby 12 000 próbek; dla bezczynności wystarczy ~600
    assert added <= 602
    # ostatnia próbka odpowiada końcowi przedziału
    assert sim.recorder.samples[-1].t == pytest.approx(start + 600.0)


def test_max_sim_time_guard():
    """Pętla ``sleep`` ponad limit czasu symulacji jest przerywana błędem."""
    sim = core.Simulation()
    sim.settings.max_sim_time = 120.0
    with pytest.raises(core.SimulationError):
        sim.advance(500.0)
    assert sim.time_exceeded is True


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


# ---------------------------------------------------------------- konwencja RC
# djitellopy/Tello: `rc a b c d` - a > 0 = W PRAWO, d > 0 = obrót W PRAWO
# (zgodnie z zegarem, tak rośnie get_yaw()). Potwierdzone w oficjalnym przykładzie
# examples/manual-control-pygame.py: K_RIGHT -> +S, K_d (clockwise) -> +S.


def _airborne() -> core.Simulation:
    sim = core.Simulation()
    ev, _, _ = sim.begin("takeoff", [])
    sim.takeoff(ev)
    return sim


def test_rc_positive_left_right_moves_right():
    """``send_rc_control(+30, 0, 0, 0)`` przesuwa drona w prawo (nie w lewo)."""
    sim = _airborne()
    start = sim.position
    ev, _, _ = sim.begin("send_rc_control", [30, 0, 0, 0, 1.0])
    sim.rc_motion(ev, 30, 0, 0, 0, 1.0)
    # yaw = 0: przód to +X, PRAWO to -Y
    assert sim.position[1] < start[1] - 10, f"dron nie poszedł w prawo: {sim.position}"
    assert abs(sim.position[0] - start[0]) < 0.5


def test_rc_negative_left_right_moves_left():
    sim = _airborne()
    ev, _, _ = sim.begin("send_rc_control", [-30, 0, 0, 0, 1.0])
    sim.rc_motion(ev, -30, 0, 0, 0, 1.0)
    assert sim.position[1] > 10, f"dron nie poszedł w lewo: {sim.position}"


def test_rc_positive_yaw_turns_clockwise():
    """``send_rc_control(0, 0, 0, +30)`` zwiększa yaw w prawo (zgodnie z zegarem)."""
    sim = _airborne()
    ev, _, _ = sim.begin("send_rc_control", [0, 0, 0, 30, 1.0])
    sim.rc_motion(ev, 0, 0, 0, 30, 1.0)
    # yaw rośnie w prawo, jak get_yaw() w Tello (30% drążka * 90 deg/s = 27 deg)
    assert sim.yaw == pytest.approx(27.0, abs=1.0), f"yaw={sim.yaw}"


def test_rc_negative_yaw_turns_counter_clockwise():
    sim = _airborne()
    ev, _, _ = sim.begin("send_rc_control", [0, 0, 0, -30, 1.0])
    sim.rc_motion(ev, 0, 0, 0, -30, 1.0)
    assert sim.yaw == pytest.approx(-27.0, abs=1.0), f"yaw={sim.yaw}"


def test_rc_forward_moves_along_nose():
    sim = _airborne()
    start = sim.position
    ev, _, _ = sim.begin("send_rc_control", [0, 30, 0, 0, 1.0])
    sim.rc_motion(ev, 0, 30, 0, 0, 1.0)
    assert sim.position[0] > start[0] + 10
    assert abs(sim.position[1] - start[1]) < 0.5


def test_rc_turn_and_forward_makes_arc():
    """Ruch w przód z jednoczesnym obrotem daje łuk (układ drona się obraca)."""
    sim = _airborne()
    ev, _, _ = sim.begin("send_rc_control", [0, 30, 0, 30, 1.0])
    sim.rc_motion(ev, 0, 30, 0, 30, 1.0)
    # obrót dodatni = w prawo od +X, czyli tor schodzi w stronę... sprawdzamy łuk:
    # pozycja różni się od prostego przelotu 15 cm wzdłuż X
    assert sim.position[0] > 10
    assert abs(sim.position[1]) > 1.0, f"brak łuku: {sim.position}"


def test_rc_integration_step_independent_of_chunk_size():
    """Ten sam ruch w jednym kroku 1 s i w 20 krokach po 50 ms daje ten sam tor."""
    one = _airborne()
    ev, _, _ = one.begin("send_rc_control", [0, 30, 0, 30, 1.0])
    one.rc_motion(ev, 0, 30, 0, 30, 1.0)

    many = _airborne()
    for _ in range(20):
        ev, _, _ = many.begin("send_rc_control", [0, 30, 0, 30, 0.05])
        many.rc_motion(ev, 0, 30, 0, 30, 0.05)

    assert many.position[0] == pytest.approx(one.position[0], abs=0.2)
    assert many.position[1] == pytest.approx(one.position[1], abs=0.2)
    assert many.yaw == pytest.approx(one.yaw, abs=0.2)
