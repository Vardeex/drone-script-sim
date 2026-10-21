"""Testy integracyjne biblioteki dronemoves w symulatorze.

Testują kontrakt między biblioteką a symulatorem: adnotacje manewrów,
grupowanie komend RC i zaplanowaną trajektorię (``planned_trail``).
Biblioteka jest instalowana w venv (``pip install -e lib/dronemoves``).
"""

import pytest

from app import runner

SOURCE = """\
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
with Pilot(t, speed=40) as p:
    p.forward(50)
    p.circle(radius=100, direction="right")
    p.hover(1)
t.land()
"""


@pytest.fixture(scope="module")
def flight():
    result = runner.run_script(SOURCE, "dronemoves_integration.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    return result.flight


def test_maneuver_annotations_are_recorded(flight):
    labels = [e["args"][0] for e in flight.events if e["command"] == "annotate"]
    assert labels[0].startswith("start: forward 50cm")
    assert any(label.startswith("start: circle r=100") for label in labels)
    assert any(label.startswith("end: circle r=100") for label in labels)
    assert all(e["status"] == "ok" for e in flight.events if e["command"] == "annotate")


def test_rc_commands_are_grouped_by_maneuver(flight):
    grouped = {}
    for event in flight.events:
        name = event.get("maneuver")
        if name:
            grouped[name] = grouped.get(name, 0) + 1
    # setki komend RC zebrane pod nazwą manewru
    circle = next((count for name, count in grouped.items() if name.startswith("circle")), 0)
    assert circle > 100
    assert any(name.startswith("forward 50cm") for name in grouped)
    assert any(name.startswith("hover") for name in grouped)


def test_planned_trail_is_exported(flight):
    trail = flight.planned_trail
    assert len(trail) > 50
    labels = {point["label"] for point in trail}
    assert any(label.startswith("forward 50cm") for label in labels)
    assert any(label.startswith("circle r=100") for label in labels)
    # plan jest ciągły w czasie i zaczyna się w punkcie startu
    times = [point["t"] for point in trail]
    assert times == sorted(times)
    assert abs(trail[0]["x"]) < 1 and abs(trail[0]["y"]) < 1


def test_drone_actually_flew(flight):
    stats = flight.stats
    assert stats["duration_s"] > 15
    assert stats["distance_cm"] > 300


def test_planned_trail_saved_in_flight_file(flight, tmp_path):
    from app import storage

    data = storage.flight_to_dict(flight, "test-id")
    assert data["planned_trail"]
    assert data["planned_trail"][0]["label"]


# ------------------------------------------- zgodność biblioteka <-> symulator
# Każdy manewr uruchamiany osobno przez runner: końcowa pozycja z telemetrii
# symulatora musi się zgadzać z pilot.position() (tolerancja 10 cm i 5 deg).

MANEUVER_TEMPLATE = """\
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
{body}
print("PILOT", json.dumps({{"x": pilot.x, "y": pilot.y, "yaw": pilot.yaw,
                            "get_yaw": t.get_yaw()}}))
t.land()
"""

MANEUVERS = [
    ("forward(100)", "pilot.forward(100)"),
    ("turn(90, radius=60)", "pilot.turn(90, radius=60)"),
    ("turn(-90, radius=60)", "pilot.turn(-90, radius=60)"),
    ("arc(180, radius=100)", "pilot.arc(180, radius=100)"),
    ("arc(-120, radius=80)", "pilot.arc(-120, radius=80)"),
    ("circle(60, left)", "pilot.circle(radius=60, direction='left')"),
    ("circle(60, right)", "pilot.circle(radius=60, direction='right')"),
    ("orbit(60, 1)", "pilot.orbit(radius=60, turns=1.0)"),
    ("slalom(3, 70, 40)", "pilot.slalom(gates=3, spacing=70, width=40)"),
    ("figure_eight(60)", "pilot.figure_eight(radius=60)"),
    ("spiral(50, 60, 3)", "pilot.spiral(radius=50, height=60, turns=3)"),
    ("path(3D)", "pilot.path([(80, 0, 0), (80, 60, 20), (0, 60, 40)])"),
]

#: tolerancja: 15 cm w poziomie i 8 deg kursu. Symulator steruje wyłącznie przez
#: ``send_rc_control`` (jak prawdziwy dron), więc wychylenia są zaokrąglane do
#: liczb całkowitych - przy długich manewrach (slalom: 169 komend) narasta błąd.
POSITION_TOLERANCE_CM = 15.0
YAW_TOLERANCE_DEG = 8.0


def _pilot_state(result):
    """Odczytaj ``PILOT {...}`` wypisane przez skrypt."""
    for line in result.stdout or []:
        text = line if isinstance(line, str) else str(line.get("text", ""))
        if text.startswith("PILOT "):
            import json

            return json.loads(text[6:])
    return None


@pytest.mark.parametrize("name,body", MANEUVERS, ids=[m[0] for m in MANEUVERS])
def test_maneuver_matches_simulator(name, body):
    """Symulator wykonuje manewr tak samo jak zakłada biblioteka.

    Sterowanie idzie wyłącznie przez ``send_rc_control`` (bez diagnostycznego
    ``send_dronemoves_profile``), czyli tak jak na prawdziwym Tello.
    """
    import math

    source = MANEUVER_TEMPLATE.format(body=body)
    result = runner.run_script(source, "maneuver.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    pilot = _pilot_state(result)
    assert pilot is not None, result.stderr

    last = result.flight.samples[-1]
    dx = last["x"] - pilot["x"]
    dy = last["y"] - pilot["y"]
    distance = math.hypot(dx, dy)
    # porównujemy kurs w konwencji API: pilot.yaw (CW+) vs tello.get_yaw()
    # (telemetria ``sample.yaw`` jest wewnętrzna, CCW+ - potrzebna scenie 3D)
    dyaw = abs(((pilot["get_yaw"] - pilot["yaw"]) % 360 + 540) % 360 - 180)

    assert distance <= POSITION_TOLERANCE_CM, (
        f"{name}: symulator ({last['x']:.1f}, {last['y']:.1f}) vs pilot "
        f"({pilot['x']:.1f}, {pilot['y']:.1f}) - różnica {distance:.1f} cm")
    assert dyaw <= YAW_TOLERANCE_DEG, (
        f"{name}: kurs get_yaw() {pilot['get_yaw']}° vs Pilot.yaw {pilot['yaw']:.1f}° "
        f"- różnica {dyaw:.1f}°")


def test_maneuver_uses_only_send_rc_control():
    """Ścieżka prawdziwego drona: żadne wywołanie ``send_dronemoves_profile``."""
    source = """
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
used = {"profile": False}
orig = pilot.backend.send_profile


def spy(*args, **kwargs):
    result = orig(*args, **kwargs)
    if result:
        used["profile"] = True
    return result


pilot.backend.send_profile = spy
pilot.turn(90, radius=60)
print("PROFILE", json.dumps(used))
t.land()
"""
    result = runner.run_script(source, "rc_only.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    text = next((line if isinstance(line, str) else line.get("text", "")
                 for line in result.stdout or []), "")
    assert '{"profile": false}' in text.replace("'", '"'), result.stdout
    # a ruch naprawdę się odbył (RC dotarło do symulatora)
    rc_events = [e for e in result.flight.events if e["command"] == "send_rc_control"]
    assert len(rc_events) > 20


def test_turn_left_goes_left_and_right_goes_right():
    """Wykrywacz odwróconego znaku / braku obrotu do układu drona.

    Konwencja publicznego API (jak Tello): **``turn(90)`` skręca w PRAWO**
    (ujemne y w układzie wewnętrznym), a ``turn(-90)`` w LEWO (dodatnie y).
    Test łapie sytuację, w której symulator ignoruje ``yaw`` przy przeliczaniu
    prędkości (tor byłby prosty) albo ma odwróconą oś boczną.
    """
    source = """
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
{body}
print("PILOT", json.dumps({{"x": pilot.x, "y": pilot.y}}))
t.land()
"""
    for body, expect_right in (("pilot.turn(90, radius=60)", True),
                               ("pilot.turn(-90, radius=60)", False)):
        result = runner.run_script(source.format(body=body), "side.py")
        assert result.status == "ok", [e["message"] for e in result.flight.errors]
        last = result.flight.samples[-1]
        pilot = _pilot_state(result)
        assert pilot is not None
        # symulator: ta sama strona co plan
        assert last["y"] * pilot["y"] > 0, (
            f"{body}: symulator y={last['y']:.1f}, pilot y={pilot['y']:.1f} "
            "(przeciwne strony - odwrócona oś boczna)")
        # i ta właściwa strona geometrycznie (prawo = −y)
        if expect_right:
            assert last["y"] < -30, f"{body}: skręt w prawo powinien dać −Y, jest {last['y']:.1f}"
        else:
            assert last["y"] > 30, f"{body}: skręt w lewo powinien dać +Y, jest {last['y']:.1f}"


def test_circle_right_stays_on_the_right_side_of_start_heading():
    """``circle(direction="right")`` krąży po prawej stronie kursu startowego.

    Kurs startowy to +X, więc prawo = −Y: **wszystkie** próbki lotu muszą mieć
    ``y ≤ 0`` (środek okręgu leży po prawej, promień 60 cm → maks. −120 cm).
    Test jest niezależny od planera: sprawdza geometrię w telemetrii.
    """
    source = """
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
pilot.circle(radius=60, direction="right")
t.land()
"""
    result = runner.run_script(source, "circle.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    ys = [s["y"] for s in result.flight.samples if s["z"] > 70]
    assert ys, "brak próbek lotu"
    assert max(ys) <= 1.0, (
        f"okrążenie w prawo wyszło na stronę +Y (lewo): max y={max(ys):.1f}")
    assert min(ys) < -40, f"okrążenie w prawo powinno wyraźnie wejść na −Y, min y={min(ys):.1f}"


def test_pilot_angles_use_tello_convention():
    """``Pilot.turn(+90)`` = skręt w PRAWO; ``Pilot.yaw`` = +90 (konwencja Tello).

    Sprawdza publiczne API ``dronemoves``: dodatni kąt/kurs = w prawo (CW),
    tak jak ``rotate_clockwise`` i ``get_yaw()`` w Tello. Wewnętrznie projekt
    trzyma kurs matematyczny (CCW+), więc konwersja musi działać na granicy.
    """
    source = """
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
{body}
print("PILOT", json.dumps({{"x": pilot.x, "y": pilot.y, "yaw": pilot.yaw,
                            "get_yaw": t.get_yaw()}}))
t.land()
"""
    # turn(+90): prawo (-y w układzie wewnętrznym), yaw = +90
    result = runner.run_script(source.format(body="pilot.turn(90, radius=60)"), "api_turn.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    pilot = _pilot_state(result)
    assert pilot is not None
    assert pilot["y"] < -30, f"turn(+90) ma kończyć po prawej stronie (−y), jest y={pilot['y']:.1f}"
    assert pilot["yaw"] == pytest.approx(90, abs=2), f"Pilot.yaw = {pilot['yaw']:.1f}, oczekiwano 90"
    assert abs(pilot["yaw"] - pilot["get_yaw"] % 360) <= 2, (
        f"Pilot.yaw ({pilot['yaw']:.1f}) musi zgadzać się z tello.get_yaw() "
        f"({pilot['get_yaw']})")

    # turn(-90): lewo (+y), yaw = 270
    result = runner.run_script(source.format(body="pilot.turn(-90, radius=60)"), "api_turn2.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    pilot = _pilot_state(result)
    assert pilot is not None
    assert pilot["y"] > 30, f"turn(-90) ma kończyć po lewej stronie (+y), jest y={pilot['y']:.1f}"
    assert min(abs(pilot["yaw"] - 270), abs(pilot["yaw"] + 90)) <= 2, (
        f"Pilot.yaw = {pilot['yaw']:.1f}, oczekiwano 270 (albo -90)")
    get_yaw_norm = pilot["get_yaw"] % 360
    assert min(abs(pilot["yaw"] - get_yaw_norm), abs(pilot["yaw"] - get_yaw_norm + 360),
               abs(pilot["yaw"] - get_yaw_norm - 360)) <= 2, (
        f"Pilot.yaw ({pilot['yaw']:.1f}) vs get_yaw ({pilot['get_yaw']})")


def test_arc_positive_turns_right():
    """``arc(+180)`` kończy po prawej stronie kursu startowego (jak ``turn``)."""
    source = """
import json
from djitellopy import Tello
from dronemoves import Pilot

t = Tello()
t.connect()
t.takeoff()
pilot = Pilot(t, speed=35)
pilot.arc(180, radius=100)
print("PILOT", json.dumps({"x": pilot.x, "y": pilot.y, "yaw": pilot.yaw}))
t.land()
"""
    result = runner.run_script(source, "arc_api.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors]
    pilot = _pilot_state(result)
    assert pilot is not None
    assert pilot["y"] < -100, f"arc(+180) ma iść na −y (prawo), jest y={pilot['y']:.1f}"
    assert pilot["yaw"] == pytest.approx(180, abs=3)
