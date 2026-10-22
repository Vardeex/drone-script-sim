"""Testy bezpieczeństwa (dronemoves 0.2.0): preflight, geofence, nadzór baterii."""

from __future__ import annotations

import pytest

from dronemoves.pilot import Pilot, SafetyError
from dronemoves.safety import (
    Geofence, PreflightError, _parse_snr, preflight, safe_start,
)


class FakeDrone:
    """Dron do testów: konfigurowalna bateria, temperatura, SNR i wysokość."""

    def __init__(self, battery=90, temperature=40, snr=60, height=0, sdk="30",
                 connect_error=None):
        self.battery = battery
        self.temperature = temperature
        self.snr = snr
        self.height = height
        self.sdk = sdk
        self.connect_error = connect_error
        self.took_off = False
        self.landed = False
        self.rc = []

    def connect(self):
        if self.connect_error:
            raise OSError(self.connect_error)
        return self

    def takeoff(self):
        self.took_off = True
        self.height = 80

    def land(self):
        self.landed = True
        self.height = 0

    def send_rc_control(self, lr, fb, ud, yaw):
        self.rc.append((lr, fb, ud, yaw))

    def get_battery(self):
        return self.battery

    def get_height(self):
        return self.height

    def get_distance_tof(self):
        return self.height

    def get_yaw(self):
        return 0

    def get_temperature(self):
        return self.temperature

    def get_lowest_temperature(self):
        return self.temperature

    def get_highest_temperature(self):
        return self.temperature

    def query_wifi_signal_noise_ratio(self):
        return self.snr

    def query_sdk_version(self):
        return self.sdk

    def get_pitch(self):
        return 0

    def get_roll(self):
        return 0

    def get_speed_x(self):
        return 0

    def get_speed_y(self):
        return 0

    def get_speed_z(self):
        return 0


def test_preflight_ok_for_good_drone():
    report = preflight(FakeDrone(battery=95, temperature=40, snr=60))
    assert report.ok
    assert report.errors == []
    names = {check.name for check in report.checks}
    assert {"bateria", "temperatura", "wifi", "na ziemi"} <= names


def test_preflight_low_battery_is_error():
    """Bateria 30 % < 50 % -> BŁĄD (start wstrzymany)."""
    report = preflight(FakeDrone(battery=30))
    assert not report.ok
    assert any("Bateria 30%" in c.message for c in report.errors)


def test_preflight_battery_warning_between_thresholds():
    """55 %: poniżej 60 % (ostrzeżenie), ale powyżej 50 % (nie błąd)."""
    report = preflight(FakeDrone(battery=55))
    assert report.ok
    assert any(c.name == "bateria" and c.level == "warning" for c in report.checks)


def test_preflight_hot_drone_is_error():
    report = preflight(FakeDrone(temperature=85))
    assert not report.ok


def test_preflight_missing_wifi_is_warning_only():
    """Brak odczytu Wi-Fi to ostrzeżenie, nie błąd."""
    class NoWifi(FakeDrone):
        query_wifi_signal_noise_ratio = None      # metoda niedostępna

    report = preflight(NoWifi())
    assert report.ok
    assert any(c.name == "wifi" and c.level == "warning" for c in report.checks)


def test_preflight_drone_in_air_is_error():
    report = preflight(FakeDrone(height=120))
    assert not report.ok


def test_preflight_plan_too_long_for_battery():
    """90 % -> zapas (90-10)*10 - 60 = 740 s; plan 900 s to ostrzeżenie."""
    report = preflight(FakeDrone(battery=90), plan_eta_s=900)
    assert any(c.name == "czas trasy" and c.level == "warning" for c in report.checks)


def test_safe_start_refuses_when_preflight_fails():
    """Bateria 30 % -> PreflightError, dron NIE startuje."""
    drone = FakeDrone(battery=30)
    with pytest.raises(PreflightError):
        safe_start(drone)
    assert drone.took_off is False


def test_safe_start_takes_off_confirmed():
    drone = FakeDrone(battery=95)
    report = safe_start(drone, confirm=True, input_fn=lambda prompt: "")
    assert drone.took_off is True
    assert report.ok


def test_parse_snr_handles_tello_formats():
    assert _parse_snr("24") == 24
    assert _parse_snr("snr:12") == 12
    assert _parse_snr(None) is None



def test_geofence_limits_height_radius_and_box():
    fence = Geofence(max_height_cm=200, max_radius_cm=300,
                     box_cm=(-100, 400, -100, 400))
    assert fence.violations(100, 0, 100) == []
    assert any("Wysokość" in v for v in fence.violations(0, 0, 250))
    assert any("Odległość" in v for v in fence.violations(350, 0, 100))
    assert any("prostokąt" in v for v in fence.violations(-150, 0, 100))
    with pytest.raises(SafetyError):
        fence.check(0, 0, 500)


def test_pilot_geofence_blocks_maneuver():
    """Geofence 100 cm blokuje manewr 200 cm przed lotem."""
    drone = FakeDrone(height=80)
    pilot = Pilot(drone, speed=40, max_height_cm=500, max_radius_cm=500)
    pilot.set_geofence(max_height_cm=500, max_radius_cm=100)
    with pytest.raises(SafetyError):
        pilot.forward(200)


def test_pilot_returns_home_within_10_cm():
    """Po locie 100 cm w przód ``return_home`` wraca do (0, 0) ±10 cm."""
    drone = FakeDrone(height=80)
    pilot = Pilot(drone, speed=40, max_height_cm=500, max_radius_cm=500)
    pilot.forward(100)
    assert pilot.position()[0] > 50            # naprawdę odleciał
    pilot.return_home()
    end = pilot.position()
    assert abs(end[0]) < 10 and abs(end[1]) < 10, end


def test_watch_battery_triggers_land():
    drone = FakeDrone(battery=15, height=80)
    pilot = Pilot(drone, speed=40)
    thread = pilot.watch_battery(min_pct=20, action="land", interval_s=0.01)
    thread.join(timeout=2.0)
    assert drone.landed is True


def test_circle_face_center_points_nose_at_center():
    """Nos obraca się razem z okrążeniem: w połowie łuku patrzy w stronę środka.

    Dron startuje w (0, 0) i leci w prawo (środek w (0, -r) = (0, -100)).
    Po połowie okrążenia jest w (0, -2r) = (0, -200), a środek jest nad nim,
    więc nos patrzy w +Y = 90° (konwencja CCW planera).
    """
    from dronemoves.calibration import TELLO_PROFILE
    from dronemoves.planner import PlanLimits, plan_circle

    traj = plan_circle(100, direction="right", face="center",
                       limits=PlanLimits(), profile=TELLO_PROFILE, speed=40)
    half = traj.samples[len(traj.samples) // 2]
    assert half.y == pytest.approx(-200, abs=5)
    assert half.yaw % 360 == pytest.approx(90, abs=8)


def test_circle_face_fixed_keeps_heading():
    from dronemoves.calibration import TELLO_PROFILE
    from dronemoves.planner import PlanLimits, plan_circle

    traj = plan_circle(100, direction="right", face="fixed",
                       limits=PlanLimits(), profile=TELLO_PROFILE, speed=40)
    assert all(abs(sample.yaw % 360) < 1e-6 for sample in traj.samples)

