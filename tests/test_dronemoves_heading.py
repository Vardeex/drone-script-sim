"""Testy fizyczne KI-1 (sprzężenie zwrotne kursu, dronemoves 0.2.1).

Wartości oczekiwane liczymy **z geometrii**, nie z wyniku programu:

* ``return_home`` wraca do startu - pozycja końcowa ±10 cm od ``(0, 0)``,
  niezależnie od kursu, na którym kończy się trasa,
* ``path`` do punktu w układzie nosa: prawo = ``-Y`` świata przy kursie 0°,
  przy kursie 90° w prawo (``rotate_clockwise(90)``) nos patrzy w ``-Y``, więc
  „przód" to ``-Y``, a „lewo" to ``-X``,
* kurs nosa po manewrze zgadza się z ``get_yaw()`` ±3°.
"""

from __future__ import annotations

import textwrap

import pytest

from app import runner

TEMPLATE = """
from djitellopy import Tello
from dronemoves import Pilot

tello = Tello()
tello.connect()
tello.takeoff()
{PRE}
pilot = Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500)
try:
    with pilot:
{BODY}
finally:
    print("KONIEC:", round(tello.get_yaw(), 1))
    tello.land()
"""


def fly(pre: str, body: str):
    """Uruchom skrypt w symulatorze; zwróć (wynik, stdout, lot)."""
    source = TEMPLATE.replace("{PRE}", pre).replace(
        "{BODY}", textwrap.indent(textwrap.dedent(body).strip(), " " * 8))
    result = runner.run_script(source, "ki1.py")
    lines = [line if isinstance(line, str) else line.get("text", "")
             for line in result.stdout or []]
    return result, lines, result.flight


def numbers(lines, prefix):
    """Wyciągnij listę liczb z linii ``PREFIX: [a, b, c]``."""
    for line in lines:
        if line.startswith(prefix) and "[" in line:
            body = line.split("[", 1)[1].split("]", 1)[0]
            return [float(v) for v in body.split(",")]
    raise AssertionError(f"brak linii {prefix} w {lines}")


def landing_position(flight):
    """Pozycja drona w chwili lądowania (ostatnia próbka w powietrzu)."""
    air = [s for s in flight.samples if s["z"] > 10]
    return air[-1]["x"], air[-1]["y"]


@pytest.mark.parametrize("final_heading,pre", [
    ("0", ""),                                # trasa prosta - kurs 0°
    ("90", "tello.rotate_clockwise(90)"),     # nos na -Y (prawo)
    ("180", "tello.rotate_clockwise(180)"),   # nos na -X
    ("270", "tello.rotate_counter_clockwise(90)"),   # nos na +Y (lewo)
])
def test_return_home_wraca_do_startu_dla_kazdego_kursu(final_heading, pre):
    """Trasa 100 cm w przód + ``return_home`` wraca do (0, 0) ±10 cm."""
    body = """
        pilot.forward(100)
        print("PO_LOCIE:", [round(v, 1) for v in pilot.position()])
        pilot.return_home()
        print("PO_POWROCIE:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly(pre, body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    after = numbers(lines, "PO_POWROCIE")
    x, y = landing_position(flight)
    # pilot i symulator muszą się zgadzać ±10 cm (pozycja rzeczywista)
    assert abs(x) < 10 and abs(y) < 10, (final_heading, x, y)
    assert abs(after[0] - x) < 10 and abs(after[1] - y) < 10, (after, x, y)


def test_return_home_po_trasach_z_obrotami_w_obie_strony():
    """forward, turn w prawo, turn w lewo, forward, return_home -> (0, 0) ±10 cm."""
    body = """
        pilot.forward(80)
        pilot.turn(90, radius=60)
        pilot.forward(60)
        pilot.turn(-90, radius=60)
        pilot.forward(50)
        pilot.return_home()
        print("PO_POWROCIE:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly("", body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    x, y = landing_position(flight)
    assert abs(x) < 10 and abs(y) < 10, (x, y)


@pytest.mark.parametrize("points,expected", [
    ("[(0, -120, 0)]", (0, -120)),     # prawo od nosa (kurs 0°) = -Y
    ("[(0, 120, 0)]", (0, 120)),       # lewo = +Y
    ("[(-120, 0, 0)]", (-120, 0)),     # za plecami = -X
])
def test_path_wzgledem_nosa_przy_kursie_zero(points, expected):
    """``path`` interpretuje punkty w układzie nosa; dron startuje z kursem 0°."""
    body = f"""
        pilot.path({points})
        print("PO:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly("", body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    x, y = landing_position(flight)
    assert abs(x - expected[0]) <= 10 and abs(y - expected[1]) <= 10, (x, y, expected)


def test_path_po_obrocie_w_prawo():
    """Po ``rotate_clockwise(90)`` nos patrzy w -Y: „przód” = -Y, „lewo” = +X.

    Geometria: nos ``(0, -1)``; oś „lewo” to nos obrócony o +90° (CCW),
    czyli ``(+1, 0)``. Dlatego punkt ``(100, 0, 0)`` daje świat ``(0, -100)``,
    a punkt ``(0, 100, 0)`` - świat ``(100, 0)``. ``get_yaw()`` zostaje 90°:
    dron nie musi się obracać, bo plan zgadza się z kursem pilota.
    """
    body = """
        pilot.path([(100, 0, 0)])
        print("PRZOD:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly("tello.rotate_clockwise(90)", body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    x, y = landing_position(flight)
    assert abs(x) <= 10 and abs(y + 100) <= 10, (x, y)
    yaw = float([line for line in lines if line.startswith("KONIEC")][0].split(":")[1])
    assert abs(((yaw - 90.0 + 180.0) % 360.0) - 180.0) <= 3.0, yaw

    body = """
        pilot.path([(0, 100, 0)])
        print("LEWO:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly("tello.rotate_clockwise(90)", body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    x, y = landing_position(flight)
    assert abs(x - 100) <= 10 and abs(y) <= 10, (x, y)


def test_return_home_z_pilota_utworzonego_po_obrocie():
    """``rotate_*`` → ``Pilot`` → lot → ``return_home`` wraca do miejsca utworzenia.

    Układ pilota: 0 = kurs w chwili utworzenia (kontrakt KI-4). Powrót ma wrócić
    do ``(0, 0)`` tego układu, czyli do punktu startu ±10 cm, niezależnie od
    kursu początkowego.
    """
    for pre in ("tello.rotate_clockwise(90)", "tello.rotate_clockwise(180)",
                "tello.rotate_counter_clockwise(90)"):
        body = """
            pilot.path([(100, 0, 0)])
            pilot.turn(90, radius=60)
            pilot.forward(60)
            pilot.return_home()
            print("PO_POWROCIE:", [round(v, 1) for v in pilot.position()])
        """
        result, lines, flight = fly(pre, body)
        assert result.status == "ok", [e["message"] for e in flight.errors]
        after = numbers(lines, "PO_POWROCIE")
        assert (after[0] ** 2 + after[1] ** 2) ** 0.5 <= 10.0, (pre, after)


def test_kurs_po_manewrze_zgodny_z_planem():
    """Po ``path`` w bok (wymaga obrotu 90°) kurs z ``get_yaw()`` = 90° ±3°."""
    body = """
        pilot.path([(0, -100, 0)])
        print("PO:", [round(v, 1) for v in pilot.position()])
    """
    result, lines, flight = fly("", body)
    assert result.status == "ok", [e["message"] for e in flight.errors]
    yaw = float(lines[[i for i, line in enumerate(lines)
                      if line.startswith("KONIEC")][0]].split(":", 1)[1])
    # nos na -Y to kurs API 90° (w prawo od +X); tolerancja 3°
    assert abs(((yaw - 90.0 + 180.0) % 360.0) - 180.0) <= 3.0, yaw
