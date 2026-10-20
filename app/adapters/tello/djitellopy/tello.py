"""Klasa ``Tello`` (mock djitellopy) - pełne API wymagane przez symulator.

Zachowanie:
  * te same nazwy i sygnatury metod co djitellopy,
  * komendy poza zakresem / w złym stanie rzucają ``TelloException``
    (tak jak odpowiedź "error" z drona w djitellopy),
  * błędy walidacji parametrów w djitellopy (np. zły kierunek ``flip``)
    rzucają ``ValueError``,
  * metody nieobsługiwane w symulacji logują ostrzeżenie i nie wywalają skryptu.
"""

from __future__ import annotations

from typing import Any


class TelloException(Exception):
    """Wyjątek zgodny z ``djitellopy.TelloException``."""


def _controller():
    """Pobierz kontroler adaptera (bez importu cyklicznego)."""
    from app.adapters.tello import runtime

    return runtime.controller()


class Tello:
    """Mock klasy ``djitellopy.Tello``."""

    def __init__(self, host: str = "192.168.10.1", retry_count: int = 3,
                 vspeed: int = 100, is_imperial: bool = False, **kwargs: Any) -> None:
        self.host = host
        self.retry_count = retry_count
        self.vspeed = vspeed
        self.is_imperial = is_imperial
        self.address = (host, 8889)
        self.state = "landed"
        self._ctrl = _controller()

    # ------------------------------------------------------------ połączenie
    def connect(self, wait_for_state: bool = True) -> "Tello":
        self._ctrl.connect()
        return self

    def end(self) -> None:
        self._ctrl.end()

    def __enter__(self) -> "Tello":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.end()

    def __del__(self) -> None:
        # djitellopy zamyka połączenie przy usuwaniu obiektu
        try:
            self._ctrl.end()
        except Exception:
            pass

    # -------------------------------------------------------------- sterowanie
    def takeoff(self, wait_for_state: bool = False) -> None:
        self._ctrl.takeoff()

    def land(self) -> None:
        self._ctrl.land()

    def emergency(self) -> None:
        self._ctrl.emergency()

    def set_speed(self, speed: int) -> None:
        self._ctrl.set_speed(speed)

    # ------------------------------------------------------------------ ruch
    def move_up(self, x: int) -> None:
        self._ctrl.move("move_up", "up", x)

    def move_down(self, x: int) -> None:
        self._ctrl.move("move_down", "down", x)

    def move_left(self, x: int) -> None:
        self._ctrl.move("move_left", "left", x)

    def move_right(self, x: int) -> None:
        self._ctrl.move("move_right", "right", x)

    def move_forward(self, x: int) -> None:
        self._ctrl.move("move_forward", "forward", x)

    def move_back(self, x: int) -> None:
        self._ctrl.move("move_back", "back", x)

    def rotate_clockwise(self, x: int) -> None:
        self._ctrl.rotate("rotate_clockwise", "cw", x)

    def rotate_counter_clockwise(self, x: int) -> None:
        self._ctrl.rotate("rotate_counter_clockwise", "ccw", x)

    def go_xyz_speed(self, x: int, y: int, z: int, speed: int) -> None:
        self._ctrl.go_xyz_speed(x, y, z, speed)

    def go_xyz_speed_mid(self, x: int, y: int, z: int, speed: int, mid: int) -> None:
        self._ctrl.unknown("go_xyz_speed_mid", [x, y, z, speed, mid])

    def curve_xyz_speed(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int,
                        speed: int) -> None:
        self._ctrl.curve_xyz_speed(x1, y1, z1, x2, y2, z2, speed)

    def curve_xyz_speed_mid(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int,
                            speed: int, mid: int) -> None:
        self._ctrl.unknown("curve_xyz_speed_mid", [x1, y1, z1, x2, y2, z2, speed, mid])

    def flip(self, direction: str) -> None:
        self._ctrl.flip(direction)

    def flip_forward(self) -> None:
        self.flip("f")

    def flip_back(self) -> None:
        self.flip("b")

    def flip_left(self) -> None:
        self.flip("l")

    def flip_right(self) -> None:
        self.flip("r")

    def send_rc_control(self, left_right_velocity: int, forward_backward_velocity: int,
                        up_down_velocity: int, yaw_velocity: int) -> None:
        self._ctrl.send_rc_control(left_right_velocity, forward_backward_velocity,
                                   up_down_velocity, yaw_velocity)

    def annotate(self, label: str) -> None:
        """Etykieta manewru (tylko symulator - prawdziwe Tello jej nie ma)."""
        self._ctrl.annotate(label)

    def send_rc_control_left(self, speed: int) -> None:
        self.send_rc_control(speed, 0, 0, 0)

    def send_rc_control_right(self, speed: int) -> None:
        self.send_rc_control(-speed, 0, 0, 0)

    def send_rc_control_forward(self, speed: int) -> None:
        self.send_rc_control(0, speed, 0, 0)

    def send_rc_control_back(self, speed: int) -> None:
        self.send_rc_control(0, -speed, 0, 0)

    def send_rc_control_up(self, speed: int) -> None:
        self.send_rc_control(0, 0, speed, 0)

    def send_rc_control_down(self, speed: int) -> None:
        self.send_rc_control(0, 0, -speed, 0)

    def send_rc_control_left_yaw(self, speed: int) -> None:
        self.send_rc_control(0, 0, 0, speed)

    def send_rc_control_right_yaw(self, speed: int) -> None:
        self.send_rc_control(0, 0, 0, -speed)

    # ----------------------------------------------------------------- odczyty
    def get_battery(self) -> int:
        return self._ctrl.get_battery()

    def get_height(self) -> int:
        return self._ctrl.get_height()

    def get_distance_tof(self) -> int:
        return self._ctrl.get_distance_tof()

    def get_speed_x(self) -> int:
        return self._ctrl.get_speed_x()

    def get_speed_y(self) -> int:
        return self._ctrl.get_speed_y()

    def get_speed_z(self) -> int:
        return self._ctrl.get_speed_z()

    def get_yaw(self) -> int:
        return self._ctrl.get_yaw()

    def get_pitch(self) -> int:
        return 0

    def get_roll(self) -> int:
        return 0

    def get_flight_time(self) -> int:
        return self._ctrl.get_flight_time()

    def get_temperature(self) -> int:
        return self._ctrl.get_temperature()

    def get_lowest_temperature(self) -> int:
        return self._ctrl.get_temperature()

    def get_highest_temperature(self) -> int:
        return self._ctrl.get_temperature()

    def get_baro(self) -> float:
        return 0.0

    def query_battery(self) -> int:
        return self.get_battery()

    def query_speed(self) -> int:
        return self._ctrl.query_speed()

    def query_height(self) -> int:
        return self.get_height()

    def query_throttle(self) -> int:
        return 0

    def get_udp_video_address(self) -> str:
        return "udp://@0.0.0.0:11111"

    # ---------------------------------------------------------------- strumień
    def streamon(self) -> None:
        self._ctrl.streamon()

    def streamoff(self) -> None:
        self._ctrl.streamoff()

    def get_frame_read(self):
        return self._ctrl.get_frame_read()

    def set_video_resolution(self, resolution: Any) -> None:
        self._ctrl.unknown("set_video_resolution", [resolution])

    def set_video_fps(self, fps: Any) -> None:
        self._ctrl.unknown("set_video_fps", [fps])

    def set_video_bitrate(self, bitrate: Any) -> None:
        self._ctrl.unknown("set_video_bitrate", [bitrate])

    def set_video_direction(self, direction: Any) -> None:
        self._ctrl.unknown("set_video_direction", [direction])

    # --------------------------------------------------- pozostałe (nieobsługiwane)
    def set_hdu(self, value: int) -> None:
        self._ctrl.unknown("set_hdu", [value])

    def set_hd_video(self, value: int) -> None:
        self._ctrl.unknown("set_hd_video", [value])

    def set_led(self, r: int, g: int, b: int) -> None:
        self._ctrl.unknown("set_led", [r, g, b])

    def send_keepalive(self) -> None:
        self._ctrl.unknown("send_keepalive", [])

    def throw_and_go(self) -> None:
        self._ctrl.unknown("throw_and_go", [])

    def palm_land(self) -> None:
        self._ctrl.unknown("palm_land", [])

    def motoron(self) -> None:
        self._ctrl.unknown("motoron", [])

    def motoroff(self) -> None:
        self._ctrl.unknown("motoroff", [])

    def set_wifi_credentials(self, ssid: str, password: str) -> None:
        self._ctrl.unknown("set_wifi_credentials", [ssid, "***"])

    def get_mission_pad_id(self) -> int:
        return -1

    def enable_mission_pads(self) -> None:
        self._ctrl.unknown("enable_mission_pads", [])

    def disable_mission_pads(self) -> None:
        self._ctrl.unknown("disable_mission_pads", [])

    def set_mission_pad_detection_direction(self, x: int) -> None:
        self._ctrl.unknown("set_mission_pad_detection_direction", [x])

    def __getattr__(self, name: str) -> Any:
        """Dowolna nieznana metoda: ostrzeżenie, bez wywalania skryptu."""
        if name.startswith("__"):
            raise AttributeError(name)

        def _unsupported(*args: Any, **kwargs: Any) -> None:
            try:
                self._ctrl.unknown(name, list(args))
            except Exception:
                pass

        return _unsupported
