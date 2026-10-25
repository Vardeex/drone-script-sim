"""Test dymny paczki przenośnej: rozpakuj, uruchom, sprawdź API, sprzątnij.

Uruchamiany lokalnie po ``build_portable.py`` oraz w ``release.yml`` na
``windows-latest`` (tam paczka jest artefaktem wydania - musi działać zanim
trafi do użytkownika).

Co sprawdzamy:

1. ZIP rozpakowuje się i zawiera ``start.bat`` oraz ``python\\python.exe``,
2. serwer startuje **z rozpakowanego katalogu** (wbudowany Python, inny port)
   i odpowiada na ``/api/health``,
3. ``basic_square.py`` (czysty djitellopy) kończy się statusem ``ok`` i ma telemetrię,
4. skrypt z ``dronemoves`` (``Pilot``) też się wykonuje - czyli biblioteka jest
   w paczce i importuje się w sandboxie.

Wszystkie oczekiwania mają limity czasu - test nie może wisieć.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_START_S = 90.0
TIMEOUT_RUN_S = 120.0

#: skrypt sprawdzający bibliotekę dronemoves w paczce
DRONEMOVES_SCRIPT = """from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
with Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500) as pilot:
    pilot.forward(100)
    pilot.turn(90, radius=60)
print("DRONEMOVES_OK")
tello.land()
"""


def _print(message: str) -> None:
    print(f"[smoke] {message}", flush=True)


def _request(url: str, payload: Optional[Dict[str, Any]] = None,
             timeout: float = 15.0) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
    return json.loads(body) if body.startswith(("{", "[")) else body


def unpack(zip_path: Path, destination: Path) -> Path:
    """Rozpakuj ZIP i zwróć katalog paczki (ten z ``start.bat``)."""
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(destination)
    for candidate in (path for path in destination.iterdir() if path.is_dir()):
        if (candidate / "start.bat").exists():
            return candidate
    raise SystemExit("w paczce brak start.bat")


def wait_health(base: str, timeout: float = TIMEOUT_START_S) -> str:
    """Czekaj na ``/api/health`` (limit czasu, czytelny błąd)."""
    deadline = time.time() + timeout
    last: Optional[Exception] = None
    while time.time() < deadline:
        try:
            return str(_request(base + "/api/health", timeout=3))
        except Exception as exc:                     # noqa: BLE001 - serwer wstaje
            last = exc
            time.sleep(0.3)
    raise AssertionError(f"serwer nie odpowiedział w {timeout:.0f} s ({last})")


def run_script(base: str, source: str, name: str) -> Dict[str, Any]:
    """Uruchom skrypt przez API i czekaj na wynik (z limitem czasu)."""
    started = _request(base + "/api/run", {"source": source, "script_name": name,
                                          "options": {}})
    run_id = started["id"]
    deadline = time.time() + TIMEOUT_RUN_S
    while time.time() < deadline:
        state = _request(base + f"/api/run/live/{run_id}")
        if state.get("status") != "running":
            assert state.get("status") == "done", state.get("error")
            return state["flight"]
        time.sleep(0.1)
    raise AssertionError(f"skrypt {name} nie zakończył się w {TIMEOUT_RUN_S:.0f} s")


def smoke(zip_path: Path, port: int, keep: bool = False) -> None:
    """Pełny test dymny: rozpakowanie, start, dwa skrypty, sprzątanie."""
    (ROOT / "tmp").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="portable_smoke_", dir=str(ROOT / "tmp")))
    process: Optional[subprocess.Popen] = None
    try:
        package = unpack(zip_path, work)
        _print(f"rozpakowano do {package}")
        python = package / "python" / "python.exe"
        assert python.exists(), "brak wbudowanego Pythona w paczce"
        version = subprocess.run([str(python), "-c", "import sys; print(sys.version)"],
                                 capture_output=True, text=True, timeout=60, check=True)
        _print(f"wbudowany Python: {version.stdout.strip().splitlines()[0]}")

        base = f"http://127.0.0.1:{port}"
        # własna grupa procesów: zatrzymanie serwera nie dotknie procesu testu
        process = subprocess.Popen(
            [str(python), "-m", "uvicorn", "app.server:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(package), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            start_new_session=True)
        health = wait_health(base)
        _print(f"/api/health: {health!r}")

        basics = package / "examples" / "basic_square.py"
        assert basics.exists(), "brak examples/basic_square.py w paczce"
        flight = run_script(base, basics.read_text(encoding="utf-8"), "basic_square.py")
        assert flight["samples"], "brak telemetrii z basic_square.py"
        _print(f"basic_square.py: {len(flight['samples'])} próbek, "
               f"{len(flight['events'])} komend")

        flight = run_script(base, DRONEMOVES_SCRIPT, "dronemoves.py")
        text = " ".join(line if isinstance(line, str) else line.get("text", "")
                        for line in flight.get("stdout") or [])
        assert "DRONEMOVES_OK" in text, text[:400]
        assert flight["samples"], "brak telemetrii ze skryptu dronemoves"
        _print(f"dronemoves: {len(flight['samples'])} próbek")
        _print("TEST DYMNY OK")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        if keep:
            _print(f"katalog testowy zostawiony: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Test dymny paczki przenośnej")
    parser.add_argument("--zip", required=True, help="plik ZIP do sprawdzenia")
    parser.add_argument("--port", type=int, default=8791,
                        help="port serwera testowego (inny niż domyślny 8765)")
    parser.add_argument("--keep", action="store_true", help="zostaw katalog testowy")
    args = parser.parse_args(list(argv) if argv is not None else None)
    started = time.perf_counter()
    try:
        smoke(Path(args.zip), args.port, keep=args.keep)
    except AssertionError as exc:
        print(f"[smoke] BŁĄD: {exc}", file=sys.stderr)
        return 1
    _print(f"cały test: {time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
