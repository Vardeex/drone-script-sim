"""Testy sandboxu runnera: wirtualny zegar, blokada sieci, timeout, izolacja."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

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
    assert result.flight.stats["distance_cm"] == pytest.approx(400.0, abs=1.0)
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


def test_watchdog_kills_script_when_parent_dies():
    """Watchdog w sandboxie: gdy proces uruchamiający skrypt zginie, skrypt też ginie."""
    helper = (
        "import json, os, sys, time\n"
        "from app import runner\n"
        "runner.run_script('while True:\\n    pass\\n', 'w.py', run_id='watch', timeout=60)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
    parent = subprocess.Popen([sys.executable, "-c", helper], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 15
        script_pid = None
        while time.time() < deadline and script_pid is None:
            procs = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"],
                capture_output=True, text=True).stdout.strip()
            items = json.loads(procs) if procs else []
            items = items if isinstance(items, list) else [items]
            for item in items:
                if item["ParentProcessId"] == parent.pid:
                    script_pid = item["ProcessId"]
                    break
            time.sleep(0.2)
        assert script_pid, "proces skryptu nie wystartował"
        # zabij proces uruchamiający skrypt (twardo, bez sprzątania)
        parent.kill()
        parent.wait(timeout=10)
        # watchdog powinien zakończyć skrypt w ciągu ~2 s
        deadline = time.time() + 10
        alive = True
        while time.time() < deadline:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {script_pid}"],
                                 capture_output=True, text=True).stdout
            alive = str(script_pid) in out
            if not alive:
                break
            time.sleep(0.3)
        assert not alive, f"skrypt {script_pid} przeżył śmierć rodzica (brak watchdoga)"
    finally:
        if parent.poll() is None:
            parent.kill()


def test_no_private_temp_paths_in_output():
    """Ścieżki z %TEMP% użytkownika nie mogą wyciekać do stdout/stderr/tracebacku."""
    source = (
        "import tempfile\n"
        "print('tmp:', tempfile.gettempdir())\n"
        "raise ValueError('blad testowy')\n"
    )
    result = runner.run_script(source, "leak.py")
    text = " ".join(row["text"] for row in result.flight.stdout + result.flight.stderr)
    text += " ".join((e.get("traceback") or "") + e.get("message", "")
                     for e in result.flight.errors)
    assert "dronesim_" not in text
    assert "\\Temp\\" not in text and "/Temp/" not in text


def test_syntax_error_line_number():
    """SyntaxError powinien wskazywać linię skryptu, nie wewnętrznego bootstrapu."""
    source = "print('ok')\ndef broken(:\n    pass\n"
    result = runner.run_script(source, "syntax.py")
    assert result.status == "error"
    assert result.flight.errors[0]["type"] == "SyntaxError"
    assert result.flight.errors[0]["line"] == 2


def test_stop_run_kills_process_and_keeps_partial_data():
    """``runner.stop_run`` zabija proces; wynik ma status 'stopped' i dane do przerwania."""
    source = (
        "from djitellopy import Tello\n"
        "import time\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "t.move_forward(100)\n"
        "print('gotowe do petli')\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    work_dir = Path(tempfile.mkdtemp(prefix="dronesim_stop_"))
    log_path = work_dir / "live.jsonl"
    box: dict = {}

    def _worker() -> None:
        box["result"] = runner.run_script(
            source, "stop.py", run_id="test-stop", timeout=60,
            log_path=log_path, work_dir=work_dir,
        )

    thread = threading.Thread(target=_worker)
    thread.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            state = runner.read_live_log(log_path)
            events = (state.get("snapshot") or {}).get("events") or []
            if "test-stop" in runner.active_processes() and len(events) >= 3:
                break
            time.sleep(0.05)
        assert runner.active_processes().get("test-stop") is not None
        assert runner.stop_run("test-stop") is True
        thread.join(timeout=15)
    finally:
        runner.stop_run("test-stop")
        shutil.rmtree(work_dir, ignore_errors=True)
    assert not thread.is_alive()
    result = box["result"]
    assert result.status == "stopped"
    assert any(e["type"] == "StoppedError" for e in result.flight.errors)
    assert result.flight.samples
    assert len(result.flight.events) >= 3
    assert "test-stop" not in runner.active_processes()
    # powtórne przerwanie zakończonego procesu => False
    assert runner.stop_run("test-stop") is False


def test_stop_all_leaves_no_orphans():
    """Po ``stop_all`` nie zostają procesy potomne (brak osieroconych pythonów)."""
    source = "import time\nwhile True:\n    time.sleep(1)\n"
    box: dict = {}

    def _worker() -> None:
        box["result"] = runner.run_script(source, "orphan.py", run_id="test-orphan", timeout=60)

    thread = threading.Thread(target=_worker)
    thread.start()
    deadline = time.time() + 10
    proc = None
    while time.time() < deadline:
        proc = runner.active_processes().get("test-orphan")
        if proc is not None and proc.poll() is None:
            break
        time.sleep(0.05)
    assert proc is not None, "proces skryptu nie wystartował"
    pid = proc.pid
    assert runner.stop_all() >= 1
    thread.join(timeout=15)
    assert not thread.is_alive()
    assert not runner.active_processes()
    # proces potomny nie żyje (na Windows sprawdzamy przez tasklist)
    if os.name == "nt":
        output = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                capture_output=True, text=True).stdout
        assert str(pid) not in output
    """Przekroczenie 500 cm = ostrzeżenie (skrypt trwa), z linią komendy."""
    source = (
        "from djitellopy import Tello\n"
        "t = Tello()\n"
        "t.connect()\n"
        "t.takeoff()\n"
        "for _ in range(10):\n"
        "    t.move_up(50)\n"
        "t.land()\n"
    )
    result = runner.run_script(source, "ceiling.py")
    assert result.status == "ok"
    assert result.flight.warnings
    assert all(w["line"] == 6 for w in result.flight.warnings)
    assert result.flight.stats["max_height_cm"] > 500
    assert result.flight.final_state == "landed"

