"""Testy kalibracji i geometrii planera (czysta matematyka, bez drona)."""

import json
import math

import pytest

from dronemoves.calibration import CalibrationProfile, TELLO_PROFILE, load_profile, save_profile
from dronemoves.planner import (PlanLimits, TrajectoryBuilder, plan_arc, plan_circle,
                                plan_figure_eight, plan_line, plan_orbit, plan_path,
                                plan_slalom, plan_spiral, plan_turn)

LIMITS = PlanLimits()
PROFILE = TELLO_PROFILE


def test_profile_roundtrip_json(tmp_path):
    profile = TELLO_PROFILE.with_measurements("forward", 100.0, 2.0)
    path = save_profile(profile, tmp_path / "profil.json")
    loaded = load_profile(path)
    assert loaded.max_speed_cm_s == pytest.approx(50.0)
    assert loaded.name == profile.name
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "dronemoves-calibration"


def test_profile_mapping_is_inverse():
    assert PROFILE.speed_to_rc(50) == 100
    assert PROFILE.rc_to_speed(100) == 50.0
    assert PROFILE.rc_to_yaw_rate(50) == 45.0
    assert PROFILE.rc_to_speed(PROFILE.speed_to_rc(25)) == pytest.approx(25.0, abs=0.3)


def test_profile_measurements_update_speed():
    profile = CalibrationProfile().with_measurements("forward", 120.0, 2.0)
    assert profile.max_speed_cm_s == pytest.approx(60.0)
    assert "kalibracja" in profile.notes


def test_line_is_smooth_and_reaches_target():
    traj = plan_line(100, limits=LIMITS, profile=PROFILE, speed=40)
    last = traj.samples[-1]
    assert (round(last.x, 1), round(last.y, 1)) == (100.0, 0.0)
    assert traj.max_speed() <= 40.5
    assert traj.max_accel() <= PROFILE.max_accel_cm_s2 * 1.2
    assert traj.samples[0].vx < 30  # rozpędzanie, nie skok prędkości


def test_turn_ninety_ends_at_radius_radius():
    traj = plan_turn(90, 80, limits=LIMITS, profile=PROFILE, speed=40)
    last = traj.samples[-1]
    assert last.x == pytest.approx(80, abs=1)
    assert last.y == pytest.approx(80, abs=1)
    assert last.yaw == pytest.approx(90, abs=1)


def test_negative_angle_turns_right():
    traj = plan_turn(-90, 80, limits=LIMITS, profile=PROFILE, speed=40)
    last = traj.samples[-1]
    assert last.x == pytest.approx(80, abs=1)
    assert last.y == pytest.approx(-80, abs=1)
    assert last.yaw == pytest.approx(270, abs=1)


def test_circle_returns_to_start_with_full_turn():
    traj = plan_circle(100, direction="right", limits=LIMITS, profile=PROFILE, speed=40)
    last = traj.samples[-1]
    assert math.hypot(last.x, last.y) <= 1.0
    total = sum(((b.yaw - a.yaw + 180) % 360) - 180
                for a, b in zip(traj.samples, traj.samples[1:]))
    assert abs(total) == pytest.approx(360, abs=2)


def test_arc_quarter_turn():
    traj = plan_arc(90, 120, limits=LIMITS, profile=PROFILE, speed=40)
    assert traj.samples[-1].x == pytest.approx(120, abs=1)
    assert traj.samples[-1].y == pytest.approx(120, abs=1)


def test_figure_eight_returns_to_start():
    traj = plan_figure_eight(80, limits=LIMITS, profile=PROFILE, speed=40)
    assert math.hypot(traj.samples[-1].x, traj.samples[-1].y) <= 1.5
    assert traj.max_speed() <= 41


def test_orbit_faces_center_and_returns():
    traj = plan_orbit(120, 1, limits=LIMITS, profile=PROFILE, speed=40)
    assert math.hypot(traj.samples[-1].x, traj.samples[-1].y) <= 1.5
    mid = traj.samples[len(traj.samples) // 2]
    direction = (math.cos(math.radians(mid.yaw)), math.sin(math.radians(mid.yaw)))
    to_center = (-mid.x, 120 - mid.y)
    norm = math.hypot(*to_center)
    assert (direction[0] * to_center[0] + direction[1] * to_center[1]) / norm > 0.98


def test_spiral_climbs_by_height():
    traj = plan_spiral(100, 100, 2, limits=LIMITS, profile=PROFILE, speed=40)
    assert traj.samples[-1].z == pytest.approx(100, abs=1)
    assert traj.samples[-1].z > traj.samples[0].z


def test_slalom_passes_through_gate_centers():
    traj = plan_slalom(4, 100, 60, limits=LIMITS, profile=PROFILE, speed=40)
    gates = traj.meta["gates"]
    assert len(gates) == 4
    for gx, gy, _ in gates:
        assert min(math.hypot(s.x - gx, s.y - gy) for s in traj.samples) <= 2.0


def test_path_hits_endpoint_and_is_smooth():
    traj = plan_path([(100, 0, 0), (200, 100, 50), (300, 0, 0)], smooth=True,
                     limits=LIMITS, profile=PROFILE, speed=40)
    last = traj.samples[-1]
    assert (last.x, last.y) == pytest.approx((300, 0), abs=1)
    assert last.z == pytest.approx(0, abs=1)
    assert traj.max_accel() <= PROFILE.max_accel_cm_s2 * 2.5


def test_builder_samples_have_rc():
    builder = TrajectoryBuilder(LIMITS, PROFILE)
    builder.curve(lambda s: (s * 50, 0.0, 0.0, 0.0), 50, 25)
    traj = builder.finish("test")
    assert traj.samples
    assert all(isinstance(s.rc[0], int) for s in traj.samples)
    assert traj.label == "test"
