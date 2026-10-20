"""Testy sandboxu runnera: wirtualny zegar, blokada sieci, timeout, izolacja."""

from __future__ import annotations

import time

import pytest

from app import runner

SQUARE = """
from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
for _ in range(4):
    tello.move_forward(100)
    tello.rotate_clockwise(90)
tello.land()
tello.end()
"""


def test_virtual_clock_is_fast(cls=None):
    """Skrypt z wieloma ``sleep`` trwa w symulacji długo, a wykonuje się migawkowo."""
    source = (
        "import time\n"
        "from djitellopy import Tello\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "for _ in range(20):\n"
        "    time.sleep(2)\n"
        "t.land()\n"
    )
    started = time.perf_counter()
    result = runner.run_script(source, "clock.py", adapter_id="tello")
    elapsed = time.perf_counter() - started
    assert result.status == "ok"
    assert result.flight.duration >= 40.0
    assert elapsed < 20.0  # 40 s snu symulacji w dużo krótszym czasie rzeczywistym
    assert result.real_seconds < 20.0


def test_script_sees_virtual_time():
    source = (
        "import time\n"
        "start = time.time()\n"
        "time.sleep(5)\n"
        "print(round(time.time() - start, 3))\n"
        "print(round(time.monotonic() - start, 3))\n"
    )
    result = runner.run_script(source, "time.py")
    texts = [row["text"] for row in result.flight.stdout]
    assert texts[0] == "5.0"
    assert texts[1] == "5.0"


def test_square_script_returns_to_start():
    result = runner.run_script(SQUARE, "square.py")
    assert result.status == "ok", result.flight.errors
    pos = result.flight.stats["final_position_cm"]
    assert pos[0] == pytest.approx(0.0, abs=1.0)
    assert pos[1] == pytest.approx(0.0, abs=1.0)
    assert round(pos[2]) == 0
    assert result.flight.stats["distance_cm"] > 400
    assert result.flight.samples[0]["t"] == 0.0


def test_network_is_blocked():
    source = (
        "import socket\n"
        "sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "sock.sendto(b'command', ('192.168.10.1', 8889))\n"
    )
    result = runner.run_script(source, "net.py")
    assert result.status == "error"
    message = " ".join(e["message"] for e in result.flight.errors)
    assert "Blokada sieci" in message
    assert any(e["type"] == "NetworkDisabled" for e in result.flight.errors)


def test_network_is_blocked_for_tcp_connect():
    source = (
        "import socket\n"
        "socket.create_connection(('8.8.8.8', 53), timeout=1)\n"
    )
    result = runner.run_script(source, "net2.py")
    assert result.status == "error"
    assert "Blokada sieci" in result.flight.errors[0]["message"]


def test_timeout_kills_infinite_loop():
    result = runner.run_script("while True:\n    pass\n", "loop.py", timeout=2.0)
    assert result.status == "timeout"
    assert result.real_seconds >= 1.9
    assert result.flight.errors[0]["type"] == "TimeoutError"
    assert result.flight.errors[0]["line"] is None


def test_out_of_range_error_has_line_number():
    source = (
        "from djitellopy import Tello\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "t.move_forward(600)\n"
        "t.land()\n"
    )
    result = runner.run_script(source, "range.py")
    assert result.status == "error"
    error = result.flight.errors[0]
    assert error["line"] == 5
    assert "poza zakresem" in error["message"]
    # skrypt przerwany - land nie wykonał się, dron w powietrzu
    assert result.flight.final_state == "airborne"


def test_move_without_takeoff_reports_error():
    source = (
        "from djitellopy import Tello\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.move_forward(100)\n"
    )
    result = runner.run_script(source, "nottakeoff.py")
    assert result.status == "error"
    assert result.flight.errors[0]["line"] == 4
    assert "takeoff" in result.flight.errors[0]["message"]


def test_stdout_and_stderr_captured():
    source = (
        "import sys\n"
        "print('linia stdout')\n"
        "print('linia stderr', file=sys.stderr)\n"
    )
    result = runner.run_script(source, "io.py")
    assert result.status == "ok"
    assert result.flight.stdout[0]["text"] == "linia stdout"
    assert result.flight.stderr[0]["text"] == "linia stderr"


def test_rc_control_moves_drone():
    source = (
        "from djitellopy import Tello\n"
        "import time\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "t.set_speed(50)\n"
        "t.send_rc_control(0, 50, 0, 0)\n"
        "time.sleep(2)\n"
        "t.send_rc_control(0, 0, 0, 0)\n"
        "time.sleep(1)\n"
        "t.land()\n"
    )
    result = runner.run_script(source, "rc.py")
    assert result.status == "ok"
    x, y, _z = result.flight.stats["final_position_cm"]
    assert x == pytest.approx(50.0, abs=1.0)
    assert y == pytest.approx(0.0, abs=1.0)


def test_mock_djitellopy_used_not_real_library():
    source = (
        "import djitellopy\n"
        "print(djitellopy.__file__)\n"
        "print(djitellopy.__version__)\n"
    )
    result = runner.run_script(source, "which.py")
    path = result.flight.stdout[0]["text"].replace("\\", "/")
    assert path.endswith("app/adapters/tello/djitellopy/__init__.py")
    assert result.flight.stdout[1]["text"].endswith("-sim")
