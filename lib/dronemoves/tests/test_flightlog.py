"""Testy rejestratora lotu (``dronemoves.flightlog``) na ``FakeDrone``.

``FakeDrone`` udaje ``djitellopy.Tello``: te same publiczne gettery, ten sam
sposób wywoływania komend, ruch w czasie rzeczywistym i **szum** pomiarów
(±0,5 cm/s), żeby sprawdzić, że rejestrator nie zakłada idealnych danych.

Oczekiwania liczymy z geometrii:
``move_forward(100)`` przy kursie 0 daje ``x ≈ +100 cm``,
po ``rotate_clockwise(90)`` (kurs w prawo) to samo „przód” idzie w ``-y``
(oś ``y`` = lewo), a ``move_up(50)`` podnosi ``z`` o 50 cm.
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import pytest

from dronemoves.flightlog import FlightRecorder


class FakeDrone:
    """Minimalny zamiennik Tello: stan + ruch liniowy w czasie rzeczywistym."""

    def __init__(self, seed: int = 7, noise: float = 0.5) -> None:
        self.height = 0.0
        self.yaw_right = 0.0             # Tello: + = w prawo
        self.battery = 87
        self.flight_time = 0
        self._x = 0.0
        self._y = 0.0
        self._noise = noise
        self._random = random.Random(seed)
        self._motion = None              # (t0, duration, dx, dy, dz, vgx, vgy)
        self._speed = 50.0

    # --- symulacja ruchu -----------------------------------------------------
    def _advance(self) -> None:
        if not self._motion:
            return
        t0, duration, dx, dy, dz, _vgx, _vgy = self._motion
        done = min(1.0, (time.monotonic() - t0) / duration)
        self._x = dx * done
        self._y = dy * done
        self.height = 80.0 + dz * done if self.height or dz else self.height
        if done >= 1.0:
            self._motion = None

    def _linear(self, forward_cm: float = 0.0, left_cm: float = 0.0,
                up_cm: float = 0.0) -> None:
        distance = math.hypot(forward_cm, left_cm)
        duration = max(0.1, distance / self._speed)
        psi = math.radians(-self.yaw_right)
        dx = forward_cm * math.cos(psi) - left_cm * math.sin(psi)
        dy = forward_cm * math.sin(psi) + left_cm * math.cos(psi)
        self._motion = (time.monotonic(), duration, dx, dy, up_cm,
                        forward_cm / duration, left_cm / duration)
        time.sleep(duration + 0.02)      # komenda blokuje, jak w djitellopy
        self._advance()

    # --- komendy ------------------------------------------------------------
    def connect(self):
        return None

    def takeoff(self):
        self.height = 80.0
        self.flight_time = 1

    def land(self):
        self.height = 0.0

    def move_forward(self, distance):
        if not 20 <= abs(distance) <= 500:
            raise ValueError(f"distance {distance} out of range")
        self._linear(forward_cm=float(distance))

    def move_up(self, distance):
        self._linear(up_cm=float(distance))

    def rotate_clockwise(self, degrees):
        self.yaw_right += degrees

    # --- gettery (jak djitellopy) -------------------------------------------
    def _noisy(self, value: float) -> float:
        return value + self._random.uniform(-self._noise, self._noise)

    def get_height(self):
        self._advance()
        return int(round(self._noisy(self.height)))

    def get_yaw(self):
        return int(round(self._noisy(self.yaw_right)))

    def get_speed_x(self):
        self._advance()
        return int(round(self._noisy(self._motion[5] if self._motion else 0.0)))

    def get_speed_y(self):
        self._advance()
        return int(round(self._noisy(self._motion[6] if self._motion else 0.0)))

    def get_speed_z(self):
        return 0

    def get_battery(self):
        return self.battery

    def get_flight_time(self):
        return self.flight_time

    def get_acceleration_x(self):
        return 0

    def get_acceleration_y(self):
        return 0

    def get_acceleration_z(self):
        return 0

    def get_distance_tof(self):
        return int(round(self.height))


# --------------------------------------------------------------------- testy
def _record(actions, interval_s: float = 0.01) -> FlightRecorder:
    """Nagraj lot: ``actions(drone)`` dostaje opakowanie rejestratora."""
    drone = FakeDrone()
    recorder = FlightRecorder(drone, interval_s=interval_s)
    with recorder:
        recorder.start()
        proxy = recorder.proxy()
        actions(proxy)
    return recorder


def test_records_samples_and_commands():
    """Rejestrator zbiera próbki i komendy (takeoff/move/land)."""
    def actions(drone):
        drone.takeoff()
        drone.move_forward(100)
        drone.land()

    recorder = _record(actions)
    assert len(recorder.samples) >= 10, len(recorder.samples)
    names = [command["command"] for command in recorder.commands]
    assert names == ["takeoff", "move_forward", "land"], names
    assert all(sample["state"] in ("idle", "airborne", "landed")
               for sample in recorder.samples)


def test_position_is_integrated_from_speed():
    """``move_forward(100)`` przy kursie 0 -> ``x`` około +100 cm (szum ±0,5 cm/s)."""
    def actions(drone):
        drone.takeoff()
        drone.move_forward(100)

    recorder = _record(actions)
    final = recorder.samples[-1]
    assert recorder.samples[-1]["z"] == pytest.approx(80.0, abs=2.0)
    assert final["x"] == pytest.approx(100.0, abs=12.0), final
    assert abs(final["y"]) < 8.0, final


def test_heading_turns_right_means_minus_y():
    """Po ``rotate_clockwise(90)`` „przód” idzie w ``-y`` (oś ``y`` = lewo)."""
    def actions(drone):
        drone.takeoff()
        drone.rotate_clockwise(90)
        drone.move_forward(60)

    recorder = _record(actions)
    final = recorder.samples[-1]
    assert final["yaw"] == pytest.approx(-90.0, abs=3.0)     # wewnętrzny CCW+
    assert final["y"] == pytest.approx(-60.0, abs=12.0), final
    assert abs(final["x"]) < 10.0, final


def test_move_up_changes_height():
    """``move_up`` podnosi ``z`` (wysokość z ``get_height``)."""
    def actions(drone):
        drone.takeoff()
        drone.move_up(40)

    recorder = _record(actions)
    assert max(s["z"] for s in recorder.samples) == pytest.approx(120.0, abs=3.0)


def test_saved_file_matches_simulator_format(tmp_path: Path):
    """Zapisany plik ma format symulatora i flagę ``source: real``."""
    def actions(drone):
        drone.takeoff()
        drone.move_forward(50)
        drone.land()

    recorder = _record(actions)
    path = recorder.save(tmp_path / "lot_real.json", flight_id="real-test")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "drone-script-simulator"
    assert payload["version"] == 1
    assert payload["source"] == "real"
    assert payload["id"] == "real-test"
    assert payload["adapter"] == "tello-real"
    # ta sama struktura próbki i zdarzenia, co lot symulowany
    for key in ("t", "x", "y", "z", "yaw", "vx", "vy", "vz", "battery", "state"):
        assert key in payload["samples"][0], key
    for key in ("index", "t", "command", "args", "status", "line", "file"):
        assert key in payload["events"][0], key
    assert payload["recorder"]["position_source"] == "estimated_from_speed"
    assert payload["stats"]["samples"] == len(payload["samples"])
    assert payload["stats"]["events"] == 3


def test_command_error_is_recorded_and_reraised():
    """Komenda odrzucona przez drona: błąd w zapisie + wyjątek leci dalej."""
    drone = FakeDrone()
    recorder = FlightRecorder(drone, interval_s=0.01)
    recorder.start()
    proxy = recorder.proxy()
    try:
        with pytest.raises(ValueError):
            proxy.move_forward(10)          # poza zakresem 20-500
    finally:
        recorder.stop()
    assert recorder.commands[-1]["command"] == "move_forward"
    assert recorder.commands[-1]["error"].startswith("ValueError")
    assert recorder.to_flight()["status"] == "error"


def test_proxy_passes_values_through():
    """Opakowanie zwraca to, co dron (np. ``get_battery`` = 87)."""
    recorder = FlightRecorder(FakeDrone(), interval_s=0.05)
    proxy = recorder.proxy()
    assert proxy.get_battery() == 87
    assert proxy.get_yaw() == 0


def test_stop_joins_thread_and_adds_final_sample():
    """``stop()`` kończy wątek (bez zawieszenia) i dopisuje próbkę końcową."""
    recorder = FlightRecorder(FakeDrone(), interval_s=0.01)
    recorder.start()
    time.sleep(0.05)
    before = len(recorder.samples)
    recorder.stop()
    assert len(recorder.samples) == before + 1
    assert recorder._thread is None


def test_mission_pad_field_present_when_supported():
    """Gdy dron wspiera maty, próbka ma pole ``mission_pad`` (None bez maty)."""

    class PadDrone(FakeDrone):
        def get_mission_pad_id(self):
            return -1

    recorder = FlightRecorder(PadDrone(), interval_s=0.01)
    with recorder:
        time.sleep(0.05)
    assert "mission_pad" in recorder.samples[-1]
    assert recorder.to_flight()["recorder"]["mission_pads"] is True
