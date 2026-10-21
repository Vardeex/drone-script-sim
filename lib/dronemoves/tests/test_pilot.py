"""Testy Pilota na fałszywym dronie (FakeDrone) - bez symulatora i djitellopy."""

import pytest

from dronemoves import Pilot, SafetyError
from dronemoves.backends.base import MotionBackend

from .conftest import FakeClock, FakeDrone, RecordingBackend


def make_pilot(drone=None, **kwargs) -> Pilot:
    clock = kwargs.pop("clock", None) or FakeClock()
    drone = drone or FakeDrone()
    pilot = Pilot(drone, **kwargs)
    pilot.executor._time = clock.time
    pilot.executor._sleep = clock.sleep
    return pilot


def test_forward_moves_and_sends_rc_more_often_than_100ms():
    drone = FakeDrone()
    pilot = make_pilot(drone)
    pilot.forward(100)
    assert pilot.position()[0] == pytest.approx(100, abs=1)
    assert len(drone.rc_calls) >= int(pilot.executor.period and 2.5 / 0.1)
    assert drone.rc_calls[-1] == (0, 0, 0, 0)  # na końcu manewru RC = 0


def test_rc_frequency_is_20hz():
    pilot = make_pilot()
    calls = []
    original = pilot.backend.rc

    def spy(vx, vy, vz, yaw_rate):
        calls.append(pilot.executor._time())
        original(vx, vy, vz, yaw_rate)

    pilot.backend.rc = spy  # type: ignore[method-assign]
    pilot.forward(40)
    deltas = [b - a for a, b in zip(calls, calls[1:])]
    assert deltas and max(deltas) <= 0.051


def test_turn_updates_pose():
    """``turn(+90)`` = skręt w PRAWO (konwencja Tello): kończy na −y, yaw = +90."""
    pilot = make_pilot()
    pilot.turn(90, radius=80)
    x, y, _ = pilot.position()
    assert (x, y) == pytest.approx((80, -80), abs=1)
    assert pilot.yaw == pytest.approx(90, abs=1)


def test_api_angle_conversion_is_centralized():
    """Konwersja API (CW+) <-> wnętrze (CCW+) jest w jednym miejscu i jest inwolucją."""
    from dronemoves.pilot import api_angle_to_internal, internal_angle_to_api

    assert api_angle_to_internal(90) == -90      # w prawo (API) = -90 wewnętrznie
    assert api_angle_to_internal(-90) == 90      # w lewo (API) = +90 wewnętrznie
    assert internal_angle_to_api(-90) == 90
    for angle in (0, 30, -45, 90, 180, 270, -270):
        assert internal_angle_to_api(api_angle_to_internal(angle)) == pytest.approx(angle)


def test_pilot_yaw_is_api_convention():
    """``Pilot.yaw`` rośnie w prawo (CW+) - tak jak ``get_yaw()`` w Tello."""
    pilot = make_pilot()
    assert pilot.yaw == pytest.approx(0, abs=1e-9)
    pilot.turn(90, radius=80)
    assert pilot.yaw == pytest.approx(90, abs=1)      # dodatni = w prawo
    pilot2 = make_pilot()
    pilot2.turn(-90, radius=80)
    assert min(abs(pilot2.yaw - 270), abs(pilot2.yaw + 90)) <= 1


def test_circle_right_keeps_the_right_side():
    """``direction="right"`` = okrążanie po prawej stronie kursu startowego (−y)."""
    pilot = make_pilot()
    traj = pilot.circle(radius=100, direction="right")
    ys = [s.y for s in traj.samples]
    assert max(ys) <= 0.5, f"circle(right) wyszło na +y: max y={max(ys):.1f}"
    assert min(ys) < -40

    pilot = make_pilot()
    traj = pilot.circle(radius=100, direction="left")
    ys = [s.y for s in traj.samples]
    assert min(ys) >= -0.5, f"circle(left) wyszło na −y: min y={min(ys):.1f}"
    assert max(ys) > 40


def test_circle_returns_to_start():
    pilot = make_pilot()
    pilot.circle(radius=100, direction="right")
    assert pilot.position()[0] == pytest.approx(0, abs=1)
    assert pilot.position()[1] == pytest.approx(0, abs=1)


def test_annotations_wrap_maneuver():
    drone = FakeDrone()
    pilot = make_pilot(drone)
    pilot.forward(50)
    assert drone.annotations[0].startswith("start:")
    assert drone.annotations[-1].startswith("end:")


def test_hover_keeps_position():
    pilot = make_pilot()
    pilot.hover(1)
    assert pilot.position() == (0.0, 0.0, 0.0)
    assert pilot.flight_time == pytest.approx(1.0, abs=0.1)


def test_sequence_is_written_to_plan():
    pilot = make_pilot()
    traj = pilot.sequence([])
    assert traj.label == "sekwencja"


def test_exception_stops_drone_and_lands():
    drone = FakeDrone(fail_after=10)
    pilot = make_pilot(drone)
    with pytest.raises(Exception):
        pilot.forward(100)
    assert pilot.backend  # sanity
    assert pilot.land_on_exit is True


def test_safety_low_battery():
    pilot = make_pilot(FakeDrone(battery=5))
    with pytest.raises(SafetyError, match="Bateria"):
        pilot.forward(50)


def test_safety_min_height():
    pilot = make_pilot(FakeDrone(height=5))
    with pytest.raises(SafetyError, match="takeoff"):
        pilot.forward(50)


def test_safety_radius_limit():
    from dronemoves.planner import PathError

    pilot = make_pilot(max_radius_cm=50)
    # planer wykrywa przekroczenie jeszcze przed lotem (czytelny błąd planowania)
    with pytest.raises((SafetyError, PathError), match="limit"):
        pilot.forward(100)
    assert pilot.position() == (0.0, 0.0, 0.0)  # nic nie poleciało


def test_preview_does_not_fly():
    from dronemoves.pilot import Maneuver

    drone = FakeDrone()
    pilot = make_pilot(drone)
    maneuver = Maneuver("circle", pilot._circle_planner(100, "right", "tangent"))
    points = pilot.preview(maneuver)
    assert len(points) > 10
    assert points[0] == pytest.approx((0, 0, 0), abs=1)
    assert drone.rc_calls == []  # preview nic nie wysyła


def test_unknown_backend_type():
    with pytest.raises(TypeError):
        Pilot(object())


def test_native_mode_requires_support():
    backend = RecordingBackend()
    pilot = Pilot(backend=backend)
    pilot.executor._time = FakeClock().time
    with pytest.raises(NotImplementedError):
        pilot.forward(50, mode="native")


def test_backend_without_native_raises():
    class Minimal(MotionBackend):
        name = "minimal"

        def rc(self, vx, vy, vz, yaw_rate):
            return None

        def stop(self):
            return None

    pilot = Pilot(backend=Minimal())
    with pytest.raises(NotImplementedError):
        pilot.turn(90, mode="native")
