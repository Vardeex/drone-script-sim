"""Test dymny instalatora i paczki: instalacja, start, API, deinstalacja.

Sprawdza **całą ścieżkę użytkownika**, lokalnie i w CI:

1. cicha instalacja (``/VERYSILENT /CURRENTUSER /DIR=<temp> /DATA=<temp>``),
2. ``DroneSim.exe`` startuje serwer (``--no-browser --no-tray``) i odpowiada
   na ``/api/health``,
3. przez API uruchamiamy ``examples/basic_square.py`` **oraz** skrypt
   dronemoves (``Pilot``) - oba muszą dolecieć i zapisać lot,
4. zamknięcie przez ``--stop-file`` (to samo co „Zakończ” w zasobniku):
   proces kończy się, port jest zwolniony, nie zostają sieroty,
5. dane użytkownika są w katalogu danych (nie w katalogu programu) i **przeżywają**
   cichą deinstalację (deinstalator pyta o ich usunięcie tylko w trybie
   interaktywnym; ``/DELETEUSERDATA=1`` usuwa je bez pytania),
6. ponowna instalacja na starszą wersję działa (aktualizacja bez deinstalacji).

Katalogi testowe są w ``tmp/`` (nic nie dotyka prawdziwych danych użytkownika).

Uruchomienie::

    python release_tools/smoke_installer.py                     # auto: dist/DroneSim-Setup-*.exe
    python release_tools/smoke_installer.py --installer dist/DroneSim-Setup-0.4.0.exe
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:                                   # uruchomienie jako moduł (testy)
    from release_tools.common import app_version, utf8_console
except ImportError:                    # uruchomienie jako skrypt
    from common import app_version, utf8_console

utf8_console()

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tmp" / "smoke-installer"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

#: skrypt dronemoves (biblioteka ruchów) - sprawdza, że paczka ma i ją
DRONEMOVES_SCRIPT = """from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
with Pilot(tello, speed=40) as pilot:
    pilot.forward(60)
    pilot.turn(90)
tello.land()
"""


def say(message: str) -> None:
    print(f"[smoke] {message}", flush=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_json(url: str, payload: Optional[Dict[str, Any]] = None,
              timeout: float = 30.0) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
    return json.loads(body) if body else None


def wait_health(port: int, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.read().decode("utf-8", "replace").strip() == "ok":
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    return False


def run_script(port: int, source: str, name: str, timeout: float = 180.0) -> Dict[str, Any]:
    """Uruchom skrypt przez API i poczekaj, aż powstanie lot z próbkami."""
    started = http_json(f"http://127.0.0.1:{port}/api/run",
                        {"source": source, "script_name": name, "save": True})
    run_id = started.get("id")
    say(f"skrypt {name}: uruchomiony ({run_id})")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # /api/run/live/{id} zna stan uruchomienia i po zakończeniu zwraca lot
            state = http_json(f"http://127.0.0.1:{port}/api/run/live/{run_id}",
                              timeout=10)
        except (urllib.error.URLError, OSError):
            state = None
        if state and state.get("status") != "running":
            if state.get("status") != "done" or state.get("error"):
                raise SystemExit(f"skrypt {name} zakończył się błędem: "
                                 f"{state.get('error')}\n{state.get('stderr')}")
            flight = state.get("flight") or {}
            samples = flight.get("samples") or []
            if not samples:
                raise SystemExit(f"skrypt {name}: lot bez próbek")
            say(f"skrypt {name}: {len(samples)} próbek, "
                f"stan {flight.get('status')}")
            return flight
        time.sleep(0.5)
    raise SystemExit(f"skrypt {name} nie skończył w {timeout:.0f} s")


def install(installer: Path, app_dir: Path, data_dir: Path) -> None:
    """Cicha instalacja dla bieżącego użytkownika do wskazanych katalogów."""
    # poprzedni deinstalator mógł jeszcze działać w tle - nie mieszaj plików
    wait_no_uninstaller(app_dir, timeout=60)
    say(f"instalacja: {installer.name} -> {app_dir}")
    command = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
               "/CURRENTUSER", f"/DIR={app_dir}", f"/DATA={data_dir}",
               f"/LOG={WORK / 'install.log'}"]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=900,
                            creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise SystemExit(f"instalator zwrócił {result.returncode}\n"
                         f"{result.stdout}\n{result.stderr}")
    exe = app_dir / "DroneSim.exe"
    if not exe.exists():
        raise SystemExit(f"po instalacji brak {exe}")
    config = app_dir / "launcher.json"
    if not config.exists():
        raise SystemExit(f"brak {config} (launcher nie zna katalogu danych)")
    payload = json.loads(config.read_text(encoding="utf-8"))
    if Path(payload.get("data_dir", "")).resolve() != data_dir.resolve():
        raise SystemExit(f"launcher.json wskazuje {payload.get('data_dir')}, "
                         f"a test używa {data_dir}")
    say(f"zainstalowano: DroneSim.exe {exe.stat().st_size // 1024} kB, "
        f"dane -> {data_dir}")


def find_uninstaller(app_dir: Path) -> Optional[Path]:
    """Deinstalator Inno Setup (``unins000.exe``, czasem ``unins001.exe``)."""
    matches = sorted(app_dir.glob("unins*.exe"))
    return matches[0] if matches else None


def wait_no_uninstaller(app_dir: Path, timeout: float = 180.0) -> None:
    """Poczekaj, aż deinstalator skończy pracę (działa w tle po zwróceniu sterowania)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not (app_dir / "DroneSim.exe").exists() and not find_uninstaller(app_dir):
            return
        time.sleep(0.5)


def uninstall(app_dir: Path, delete_data: bool = False) -> None:
    """Cicha deinstalacja (opcjonalnie z usunięciem danych użytkownika)."""
    uninstaller = find_uninstaller(app_dir)
    if uninstaller is None:
        raise SystemExit(f"brak deinstalatora w {app_dir}")
    extra = ["/DELETEUSERDATA=1"] if delete_data else []
    say(f"deinstalacja {uninstaller.name} "
        f"(dane {'usuwane' if delete_data else 'zachowane'})")
    result = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                             "/NORESTART", f"/LOG={WORK / 'uninstall.log'}", *extra],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=900,
                            creationflags=CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise SystemExit(f"deinstalator zwrócił {result.returncode}\n"
                         f"{result.stdout}\n{result.stderr}")
    wait_no_uninstaller(app_dir)
    if (app_dir / "DroneSim.exe").exists():
        raise SystemExit("deinstalator nie usunął DroneSim.exe")


def start_and_test(app_dir: Path, data_dir: Path, port: int) -> None:
    """Uruchom DroneSim.exe, sprawdź health + dwa skrypty, zamknij grzecznie."""
    stop_file = WORK / "stop.txt"
    stop_file.unlink(missing_ok=True)
    exe = app_dir / "DroneSim.exe"
    say(f"start: {exe.name} --no-tray --no-browser --port {port}")
    process = subprocess.Popen(
        [str(exe), "--no-tray", "--no-browser", "--port", str(port),
         "--stop-file", str(stop_file)],
        cwd=str(app_dir), creationflags=CREATE_NO_WINDOW)
    try:
        if not wait_health(port):
            raise SystemExit("serwer nie odpowiedział na /api/health")
        say("health: ok")

        basic = (ROOT / "examples" / "basic_square.py").read_text(encoding="utf-8")
        first = run_script(port, basic, "basic_square.py")
        second = run_script(port, DRONEMOVES_SCRIPT, "dronemoves_demo.py")
        if len(first["samples"]) < 10 or len(second["samples"]) < 10:
            raise SystemExit("loty mają za mało próbek")

        flights = data_dir / "flights"
        saved = sorted(flights.glob("*.json")) if flights.exists() else []
        if len(saved) < 2:
            raise SystemExit(f"loty nie zapisały się w {flights} (jest {len(saved)})")
        say(f"loty w katalogu danych: {len(saved)} plików")

        stop_file.write_text("stop", encoding="utf-8")
        code = process.wait(timeout=120)
        say(f"launcher zakończony (kod {code})")
        if code != 0:
            raise SystemExit(f"launcher zwrócił {code}")
    finally:
        if process.poll() is None:
            process.kill()
    time.sleep(1.5)
    if port_open(port):
        raise SystemExit(f"port {port} nadal zajęty - został proces sierotny")
    say("port wolny, brak sierot")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Test dymny instalatora DroneSim")
    parser.add_argument("--installer", default=None, help="plik DroneSim-Setup-*.exe")
    parser.add_argument("--keep", action="store_true",
                        help="zostaw katalogi testowe (diagnostyka)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    version = app_version()
    installer = (Path(args.installer) if args.installer
                 else ROOT / "dist" / f"DroneSim-Setup-{version}.exe")
    if not installer.exists():
        raise SystemExit(f"brak instalatora {installer} - uruchom build_installer.py")
    size_mb = installer.stat().st_size / 1024 / 1024
    say(f"instalator: {installer} ({size_mb:.1f} MB)")

    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    app_dir = WORK / "app"
    data_dir = WORK / "data"
    port = free_port()
    started = time.perf_counter()
    try:
        install(installer, app_dir, data_dir)
        start_and_test(app_dir, data_dir, port)

        # deinstalacja NIE może skasować danych użytkownika
        uninstall(app_dir)
        if not (data_dir / "flights").exists():
            raise SystemExit(f"deinstalacja usunęła dane użytkownika: {data_dir}")
        say(f"dane po deinstalacji: {data_dir} (zachowane)")

        # idempotencja: instalacja na (nieistniejącą już) starszą wersję + usunięcie danych
        install(installer, app_dir, data_dir)
        if not list((data_dir / "flights").glob("*.json")):
            raise SystemExit("aktualizacja nadpisała dane użytkownika")
        uninstall(app_dir, delete_data=True)
        if data_dir.exists():
            raise SystemExit(f"/DELETEUSERDATA=1 nie usunął {data_dir}")
        say("/DELETEUSERDATA=1: dane usunięte")
    finally:
        elapsed = time.perf_counter() - started
        # po nieudanym teście nie zostawiamy wpisu w „Aplikacje i funkcje”
        if (app_dir / "unins000.exe").exists():
            try:
                subprocess.run([str(app_dir / "unins000.exe"), "/VERYSILENT",
                                "/SUPPRESSMSGBOXES", "/NORESTART",
                                "/DELETEUSERDATA=1"],
                               capture_output=True, timeout=600,
                               creationflags=CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError) as exc:
                say(f"nie udało się posprzątać po teście: {exc}")
        if args.keep:
            say(f"katalogi testowe zostawione w {WORK}")
        else:
            shutil.rmtree(WORK, ignore_errors=True)
    say(f"OK - wszystko przeszło w {elapsed:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
