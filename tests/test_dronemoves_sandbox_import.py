"""Testy biblioteki ``dronemoves`` w sandboxie runnera.

Regresja: na czystej instalacji (setup.bat, CI) każdy skrypt z
``from dronemoves import ...`` kończył się ``ModuleNotFoundError``, bo
``lib/dronemoves`` nie było instalowane (lokalnie maskowała to ręczna
instalacja ``pip install -e``). Test uruchamia import w **tym samym
interpreterze, którego używa runner** (podproces), więc łapie brak zależności
także wtedy, gdy pakiet jest tylko w ``site-packages`` środowiska.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app import paths, runner


def run_script_and_report(label: str, code: str):
    """Uruchom skrypt w runnerze; zwróć (status, tekst błędu, stdout)."""
    result = runner.run_script(code, f"{label}.py")
    errors = [str(e.get("message", "")) for e in result.flight.errors]
    output = "".join(line if isinstance(line, str) else line.get("text", "")
                     for line in result.stdout or [])
    return result.status, errors, output


DRONEMOVES_PROBE = """
import dronemoves
from dronemoves import Pilot, safe_start, preflight, Geofence

print("DRONEMOVES_OK", dronemoves.__version__)
print("MA_API", all(callable(f) for f in (Pilot, safe_start, preflight, Geofence)))
"""


def test_dronemoves_importable_in_sandbox():
    """``import dronemoves`` musi działać w podprocesie skryptu (nie tylko w testach).

    Ta sama biblioteka jest potrzebna przykładom, kodowi z planera (``safe_start``)
    i testom integracyjnym. Komunikat błędu wskazuje naprawę, jeśli zależność
    zniknie z ``requirements.txt``.
    """
    status, errors, output = run_script_and_report("import_dronemoves", DRONEMOVES_PROBE)
    if status != "ok" or "DRONEMOVES_OK" not in output:
        joined = "\n".join(errors) or output
        hint = (
            "\n\nBiblioteka 'dronemoves' nie jest dostępna w środowisku symulatora.\n"
            "Naprawa: 'pip install -r requirements.txt' w katalogu projektu "
            "(requirements.txt zawiera '-e ./lib/dronemoves')."
        )
        if isinstance(joined, str) and "ModuleNotFoundError" in joined:
            pytest.fail(f"Sandbox nie widzi dronemoves:\n{joined}{hint}")
        pytest.fail(f"Skrypt kontrolny nie wykonał się (status={status}):\n{joined}{hint}")
    text = output.replace("DRONEMOVES_OK", "\nDRONEMOVES_OK").replace("MA_API", "\nMA_API")
    values = {}
    for line in text.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and parts[0] in ("DRONEMOVES_OK", "MA_API"):
            values[parts[0]] = parts[1].strip()
    assert values.get("MA_API") == "True", output
    assert values.get("DRONEMOVES_OK"), output


def test_dronemoves_package_version_matches_library():
    """Wersja widziana w sandboxie = wersja z ``lib/dronemoves`` (nie stara kopia)."""
    from lib.dronemoves.dronemoves import __version__ as local_version

    result = subprocess.run(
        [sys.executable, "-c", "import dronemoves; print(dronemoves.__version__)"],
        cwd=str(paths.PROJECT_ROOT), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == local_version, (
        f"w środowisku jest dronemoves {result.stdout.strip()}, "
        f"a w lib/dronemoves {local_version} - uruchom "
        f"'pip install -r requirements.txt'")


def test_maneuver_from_dronemoves_runs_in_simulator():
    """Skrypt z ``dronemoves.Pilot`` wykonuje realny lot (nie tylko import)."""
    code = """
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
with Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500) as pilot:
    pilot.forward(80)
    pilot.turn(90, radius=60)
print("PO_LOCIE", [round(v, 1) for v in pilot.position()])
tello.land()
"""
    status, errors, output = run_script_and_report("lot_dronemoves", code)
    assert status == "ok", errors
    assert "PO_LOCIE" in output, output
    # geometria: forward(80) + łuk 90° o promieniu 60 cm pokonują drogę,
    # więc dron nie może zostać w punkcie startu
    payload = output.split("PO_LOCIE", 1)[1].split("[", 1)[1].split("]", 1)[0]
    x, y = [float(v) for v in payload.split(",")[:2]]
    assert (x * x + y * y) ** 0.5 > 50.0, (x, y)


@pytest.mark.parametrize("module", ["dronemoves", "dronemoves.planner", "dronemoves.pilot",
                                    "dronemoves.executor", "dronemoves.safety",
                                    "dronemoves.backends.base"])
def test_all_public_submodules_importable(module):
    """Wszystkie podmoduły używane przez skrypty i planer importują się w sandboxie."""
    code = f"import {module}\nprint('IMPORT_OK {module}')\n"
    status, errors, output = run_script_and_report(f"import_{module.replace('.', '_')}", code)
    assert status == "ok", errors
    assert f"IMPORT_OK {module}" in output, output
