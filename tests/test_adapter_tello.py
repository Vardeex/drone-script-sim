"""Testy adaptera Tello: limity zakresów, API mocka, ostrzeżenia."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import paths
from app.adapters.base import detect_adapter, get_adapter, list_adapters
from app.adapters.tello.adapter import TelloController
from app.adapters.tello.limits import LIMITS
from app.sim import core


@pytest.fixture()
def ctrl():
    return TelloController(core.Simulation())


def _takeoff(ctrl: TelloController) -> None:
    ctrl.connect()
    ctrl.takeoff()


def test_registry_lists_tello():
    ids = [info.id for info in list_adapters()]
    assert "tello" in ids
    adapter = get_adapter("tello")
    assert adapter.module_names == ("djitellopy",)
    assert adapter.limits()["move_max_cm"] == 500


def test_detect_adapter_by_import():
    assert detect_adapter("from djitellopy import Tello\n").id == "tello"
    assert detect_adapter("import os\n").id == "tello"  # fallback


@pytest.mark.parametrize("distance", [19, 501, 0, -100, 9999])
def test_move_distance_out_of_range(ctrl, distance):
    _takeoff(ctrl)
    with pytest.raises(core.SimulationError):
        ctrl.move("move_forward", "forward", distance)
    event = ctrl.sim.recorder.events[-1]
    assert event.status == "error"
    assert "poza zakresem" in event.message
    assert ctrl.sim.recorder.errors
    # dron nie wykonał ruchu
    assert ctrl.sim.position[0] == pytest.approx(0.0)


@pytest.mark.parametrize("distance", [20, 500])
def test_move_distance_limits_accepted(ctrl, distance):
    _takeoff(ctrl)
    ctrl.move("move_forward", "forward", distance)
    assert ctrl.sim.position[0] == pytest.approx(distance)


@pytest.mark.parametrize("degrees", [0, 361, -5])
def test_rotate_out_of_range(ctrl, degrees):
    _takeoff(ctrl)
    with pytest.raises(core.SimulationError):
        ctrl.rotate("rotate_clockwise", "cw", degrees)


@pytest.mark.parametrize("speed", [9, 101, 0])
def test_set_speed_out_of_range(ctrl, speed):
    with pytest.raises(core.SimulationError):
        ctrl.set_speed(speed)


def test_set_speed_valid_changes_move_speed(ctrl):
    _takeoff(ctrl)
    ctrl.set_speed(100)
    event_before = len(ctrl.sim.recorder.events)
    ctrl.move("move_forward", "forward", 100)
    move_event = ctrl.sim.recorder.events[event_before]
    assert move_event.duration == pytest.approx(1.0)


def test_rc_out_of_range(ctrl):
    with pytest.raises(core.SimulationError):
        ctrl.send_rc_control(101, 0, 0, 0)


def test_move_before_takeoff_is_error(ctrl):
    ctrl.connect()
    with pytest.raises(core.SimulationError):
        ctrl.move("move_forward", "forward", 100)
    assert ctrl.sim.recorder.errors[0]["type"] == "SimulationError"


def test_takeoff_height_and_state(ctrl):
    _takeoff(ctrl)
    assert 80 <= ctrl.sim.position[2] <= 100  # takeoff 0,8-1 m
    assert ctrl.sim.state == core.STATE_AIRBORNE
    ctrl.land()
    assert ctrl.sim.state == core.STATE_LANDED
    assert ctrl.sim.position[2] == pytest.approx(0.0)


def test_double_takeoff_raises(ctrl):
    _takeoff(ctrl)
    with pytest.raises(core.SimulationError):
        ctrl.takeoff()


def test_unsupported_command_only_warns(ctrl):
    _takeoff(ctrl)
    ctrl.unknown("set_led", [255, 0, 0])
    assert ctrl.sim.recorder.warnings[0]["message"].startswith("Komenda 'set_led' nie jest obsługiwana")
    assert not ctrl.sim.recorder.errors
    event = ctrl.sim.recorder.events[-1]
    assert event.status == "warning"


def test_getters_return_values(ctrl):
    _takeoff(ctrl)
    assert ctrl.get_battery() == pytest.approx(100, abs=1)
    assert ctrl.get_height() == pytest.approx(80, abs=1)
    ctrl.rotate("rotate_counter_clockwise", "ccw", 90)
    assert ctrl.get_yaw() == pytest.approx(90, abs=1)
    frame = ctrl.get_frame_read()
    assert frame.frame.frame is None


def test_flip_invalid_direction_raises_value_error(ctrl):
    _takeoff(ctrl)
    with pytest.raises(ValueError):
        ctrl.flip("diagonal")


def test_go_xyz_speed_beyond_limit_raises_value_error(ctrl):
    _takeoff(ctrl)
    with pytest.raises(ValueError):
        ctrl.go_xyz_speed(0, 0, 600, 50)


def test_mock_module_importable_from_adapter_path():
    """``djitellopy`` z katalogu adaptera to mock (nie instalowany w venv)."""
    mock_root = str(paths.ADAPTERS_DIR / "tello")
    sys.path.insert(0, mock_root)
    try:
        for name in list(sys.modules):
            if name == "djitellopy" or name.startswith("djitellopy."):
                del sys.modules[name]
        import djitellopy  # noqa: F401

        assert getattr(djitellopy, "__version__", "").endswith("-sim")
        assert djitellopy.available() is False
        assert hasattr(djitellopy, "Tello") and hasattr(djitellopy, "TelloException")
    finally:
        for name in list(sys.modules):
            if name == "djitellopy" or name.startswith("djitellopy."):
                del sys.modules[name]
        sys.path.remove(mock_root)


def test_tello_limits_values():
    assert (LIMITS.move_min_cm, LIMITS.move_max_cm) == (20, 500)
    assert (LIMITS.rotate_min_deg, LIMITS.rotate_max_deg) == (1, 360)
    assert (LIMITS.speed_min, LIMITS.speed_max) == (10, 100)
