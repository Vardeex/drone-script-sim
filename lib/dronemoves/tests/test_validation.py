"""Testy walidacji manewrów (czytelne wyjątki przed startem)."""

import pytest

from dronemoves.calibration import TELLO_PROFILE
from dronemoves.planner import (PlanLimits, PathError, plan_circle, plan_line, plan_path,
                                plan_slalom, plan_spiral, plan_turn)

LIMITS = PlanLimits()
PROFILE = TELLO_PROFILE


@pytest.mark.parametrize("radius", [5, 10, 19])
def test_turn_rejects_too_small_radius(radius):
    with pytest.raises(PathError, match="za mały"):
        plan_turn(90, radius, limits=LIMITS, profile=PROFILE, speed=40)


def test_turn_rejects_impossible_yaw_rate_with_hint():
    with pytest.raises(PathError) as err:
        plan_turn(90, 20, limits=LIMITS, profile=PROFILE, speed=50)
    message = str(err.value)
    assert "°/s" in message
    assert "Zwiększ promień" in message or "zmniejsz prędkość" in message


def test_turn_rejects_zero_angle():
    with pytest.raises(PathError):
        plan_turn(0, 80, limits=LIMITS, profile=PROFILE, speed=40)


def test_circle_rejects_bad_direction():
    with pytest.raises(PathError):
        plan_circle(100, direction="up", limits=LIMITS, profile=PROFILE, speed=40)


def test_limits_reject_long_flight():
    with pytest.raises(PathError, match="limit"):
        plan_line(900, limits=LIMITS, profile=PROFILE, speed=40)


def test_spiral_rejects_exceeding_height():
    with pytest.raises(PathError, match="Wysokość"):
        plan_spiral(100, 400, 1, limits=LIMITS, profile=PROFILE, speed=40)


def test_path_requires_two_points():
    with pytest.raises(PathError):
        plan_path([(0, 0, 0)], limits=LIMITS, profile=PROFILE, speed=40)


def test_slalom_rejects_zero_gates():
    with pytest.raises(PathError):
        plan_slalom(0, limits=LIMITS, profile=PROFILE, speed=40)
