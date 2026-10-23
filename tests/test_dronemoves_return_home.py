"""Test regresyjny KI-1: ``return_home`` po KAŻDEJ trasie kończy przy starcie.

Kluczowe: trasa musi kończyć się kursem **≠ 0°**, bo błąd podwójnego obrotu
w ``_path_planner`` był niewidoczny przy kursie 0°. Oczekiwanie ≤ 10 cm od
``(0, 0)`` - ``return_home`` ma wrócić do punktu startu.
"""

from __future__ import annotations

import pytest

from app import runner

TEMPLATE = """
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
pilot = Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500)
with pilot:
{body}
    print("KURS_PRZED_POWROTEM:", round(tello.get_yaw(), 1))
    pilot.return_home()
tello.land()
"""

ROUTES = {
    "turn90": """
    pilot.forward(150)
    pilot.turn(90, radius=60)
    pilot.forward(100)
    """,
    "turn180": """
    pilot.forward(120)
    pilot.turn(180, radius=60)
    pilot.forward(80)
    """,
    "mieszany": """
    pilot.forward(80)
    pilot.turn(90, radius=60)
    pilot.forward(60)
    pilot.turn(-90, radius=60)
    pilot.forward(50)
    pilot.turn(180, radius=60)
    """,
    "slalom_kolko": """
    pilot.slalom(gates=3, spacing=60, width=40)
    pilot.circle(radius=60, direction="left")
    pilot.turn(-90, radius=60)
    """,
    "path_po_turnie": """
    pilot.turn(90, radius=60)
    pilot.path([(0, -100, 0)])
    """,
}


def fly(name: str):
    """Uruchom trasę w symulatorze; zwróć (wynik, linie stdout, lot)."""
    body = ROUTES[name].strip("\n")
    result = runner.run_script(TEMPLATE.replace("{body}", body), f"{name}.py")
    lines = [line if isinstance(line, str) else line.get("text", "")
             for line in result.stdout or []]
    return result, lines, result.flight


def value_of(lines, prefix):
    """Pierwsza liczba z linii ``PREFIX: 12.3``."""
    line = next(item for item in lines if item.startswith(prefix))
    return float(line.split(":", 1)[1].strip())


@pytest.mark.parametrize("name", list(ROUTES))
def test_return_home_po_trze_konczacej_sie_innym_kursem(name: str):
    """Po każdej z tras ``return_home`` wraca do startu ≤ 10 cm.

    Trasy kończą się kursem ≠ 0°, więc podwójny obrót (błąd 0.2.1) wysyłał
    drona 3,7-6,2 m od startu i test go wykrywa.
    """
    result, lines, flight = fly(name)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    heading = value_of(lines, "KURS_PRZED_POWROTEM")
    assert abs(((heading + 180.0) % 360.0) - 180.0) > 10, (
        f"trasa {name} kończy się kursem ~0° - test nie wykryje podwójnego obrotu")
    air = [s for s in flight.samples if s["z"] > 10]
    x, y = air[-1]["x"], air[-1]["y"]
    assert (x * x + y * y) ** 0.5 <= 10.0, (name, x, y)


@pytest.mark.parametrize("angle,expected", [
    # turn(90) = skręt w prawo, r=60: środek łuku w (0,-60), koniec łuku (60,-60),
    # nos w -Y. Punkt (0,-100,0) to 100 cm w prawo od nosa, czyli -X:
    # (60-100, -60) = (-40, -60).
    (90, (-40, -60)),
    # turn(-90) = skręt w lewo: koniec łuku (60, +60), nos w +Y; „prawo od nosa”
    # to +X: (60+100, 60) = (160, 60).
    (-90, (160, 60)),
])
def test_path_po_turnie_konczy_zgodnie_z_geometria(angle, expected):
    """``turn(angle, radius=60)`` + ``path([(0, -100, 0)])`` - pozycja z geometrii."""
    body = f"""
    pilot.turn({angle}, radius=60)
    pilot.path([(0, -100, 0)])
    """
    source = TEMPLATE.replace("{body}", body.strip("\n")).replace(
        '    print("KURS_PRZED_POWROTEM:", round(tello.get_yaw(), 1))\n', "").replace(
        "    pilot.return_home()\n", "")
    result = runner.run_script(source, "geom.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    air = [s for s in result.flight.samples if s["z"] > 10]
    x, y = air[-1]["x"], air[-1]["y"]
    assert abs(x - expected[0]) <= 12 and abs(y - expected[1]) <= 12, (x, y, expected)
