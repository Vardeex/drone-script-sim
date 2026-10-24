"""Testy losowe lotów: generator scenariuszy z powtarzalnym ziarnem.

Cel: złapać błędy, których nie przewidzieliśmy w testach pisanych ręcznie.
Bez nowych zależności - ``random.Random(seed)``; **ziarno jest w nazwie
przypadku** (``forward-turn90-...-seed12345``), więc każdy błąd da się odtworzyć:

    pytest tests/test_random_flights.py -k "seed12345"

Kryteria (liczone z geometrii, nie z wyniku programu):

* ``pilot.position()`` vs symulator ≤ **15 cm** i kurs ≤ **5°**,
* po ``return_home()`` dron ≤ **10 cm** od miejsca utworzenia pilota,
* żaden manewr nie przekracza limitów bez ``SafetyError`` (wysokość/geofence),
  czyli lot kończy się ``status="ok"`` albo oczekiwanym ``SafetyError``.

Dwa poziomy: wariant **szybki** (20 scenariuszy) w zwykłym zestawie i pełny
(**200** + 100 tras planera) pod markerem ``slow``.
"""

from __future__ import annotations

import math
import random
import re
import textwrap
from dataclasses import dataclass

import pytest

from app import runner

#: tolerancja pozycji pilota wobec symulatora [cm] (specyfikacja testu losowego)
TOL_POSITION_CM = 15.0
#: tolerancja kursu [°]
TOL_HEADING_DEG = 5.0
#: tolerancja ``return_home`` [cm]
TOL_RETURN_HOME_CM = 10.0

#: ziarna dla wariantu szybkiego (zwykłe testy) i pełnego (marker ``slow``)
FAST_SEEDS = list(range(1, 21))
SLOW_SEEDS = list(range(1, 201))
SLOW_ROUTE_SEEDS = list(range(1000, 1100))


@dataclass
class Maneuver:
    """Jeden manewr scenariusza: nazwa i wywołanie w Pythonie."""

    name: str
    code: str


def random_maneuver(rng: random.Random) -> Maneuver:
    """Wylosuj manewr z dozwolonymi parametrami (zakresy jak w README biblioteki)."""
    kind = rng.choice([
        "forward", "turn", "arc", "circle", "slalom", "orbit",
        "figure_eight", "spiral", "path", "hover",
    ])
    if kind == "forward":
        distance = rng.choice([20, 30, 40, 50, 60, 80, 100, 120])
        return Maneuver(kind, f"pilot.forward({distance})")
    if kind == "turn":
        angle = rng.choice([-180, -135, -90, -45, 45, 90, 135, 180])
        radius = rng.choice([40, 50, 60, 80, 100])
        return Maneuver(kind, f"pilot.turn({angle}, radius={radius})")
    if kind == "arc":
        angle = rng.choice([-120, -90, -60, 60, 90, 120])
        radius = rng.choice([50, 60, 80, 100])
        return Maneuver(kind, f"pilot.arc({angle}, radius={radius})")
    if kind == "circle":
        radius = rng.choice([40, 50, 60, 80])
        direction = rng.choice(["right", "left"])
        return Maneuver(kind, f"pilot.circle(radius={radius}, direction='{direction}')")
    if kind == "slalom":
        gates = rng.choice([2, 3, 4])
        spacing = rng.choice([50, 60, 80])
        width = rng.choice([30, 40, 50])
        return Maneuver(kind, f"pilot.slalom(gates={gates}, spacing={spacing}, width={width})")
    if kind == "orbit":
        radius = rng.choice([50, 60, 80, 100])
        turns = rng.choice([0.5, 1.0])
        direction = rng.choice(["right", "left"])
        return Maneuver(kind, f"pilot.orbit(radius={radius}, turns={turns}, "
                              f"direction='{direction}')")
    if kind == "figure_eight":
        radius = rng.choice([40, 50, 60, 80])
        return Maneuver(kind, f"pilot.figure_eight(radius={radius})")
    if kind == "spiral":
        radius = rng.choice([40, 60, 80])
        height = rng.choice([40, 60, 80])
        turns = rng.choice([1.0, 2.0])
        return Maneuver(kind, f"pilot.spiral(radius={radius}, height={height}, turns={turns})")
    if kind == "path":
        count = rng.randint(1, 4)
        points = []
        for _ in range(count):
            points.append((rng.choice([-80, -60, -40, 0, 40, 60, 80]),
                           rng.choice([-60, -40, 0, 40, 60]),
                           rng.choice([-20, 0, 0, 20])))
        rendered = ", ".join(f"({x}, {y}, {z})" for x, y, z in points)
        return Maneuver(kind, f"pilot.path([{rendered}])")
    seconds = rng.choice([0.5, 1.0, 2.0])
    return Maneuver("hover", f"pilot.hover({seconds})")


@dataclass
class Scenario:
    """Losowy scenariusz: kurs startowy, manewry i nazwa z ziarnem."""

    seed: int
    start_yaw: int
    maneuvers: list

    @property
    def name(self) -> str:
        kinds = "-".join(item.name for item in self.maneuvers)
        return f"start{self.start_yaw}-{kinds}-seed{self.seed}"

    def script(self) -> str:
        """Skrypt dla symulatora (sandbox: mock ``djitellopy`` + ``dronemoves``)."""
        lines = [
            "from djitellopy import Tello",
            "from dronemoves import Pilot",
            "",
            "tello = Tello()",
            "tello.connect()",
            "tello.takeoff()",
            "tello.move_up(40)                 # miejsce na manewry w górę i w dół",
        ]
        if self.start_yaw:
            method = ("rotate_clockwise" if self.start_yaw > 0
                      else "rotate_counter_clockwise")
            lines.append(f"tello.{method}({abs(self.start_yaw)})")
        lines += [
            "pilot = Pilot(tello, speed=40, max_height_cm=500, max_radius_cm=500)",
            "with pilot:",
        ]
        lines += [f"    {item.code}" for item in self.maneuvers]
        lines += [
            '    print("PILOT", [round(v, 1) for v in pilot.position()],',
            "          round(pilot.yaw, 1))",
            "    pilot.return_home()",
            '    print("DOM", [round(v, 1) for v in pilot.position()])',
            "tello.land()",
        ]
        return "\n".join(lines) + "\n"


def make_scenario(seed: int) -> Scenario:
    """Zbuduj scenariusz z ziarna (ten sam seed = ten sam scenariusz)."""
    rng = random.Random(seed)
    start_yaw = rng.choice([0, 0, 90, 180, -90, 45, -135])
    count = rng.randint(1, 6)
    maneuvers = [random_maneuver(rng) for _ in range(count)]
    return Scenario(seed=seed, start_yaw=start_yaw, maneuvers=maneuvers)


MARKER_PATTERN = re.compile(
    r"(?P<marker>PILOT|DOM)\s*\[\s*(?P<x>-?[\d.]+)\s*,\s*(?P<y>-?[\d.]+)\s*,"
    r"\s*(?P<z>-?[\d.]+)\s*\](?:\s*(?P<yaw>-?[\d.]+))?"
)


def parse_marker(output: str, marker: str) -> list:
    """Wyciągnij liczby z linii ``MARKER [x, y, z] yaw``.

    Stdout sandboxu bywa zlepiony w jedną linię, więc nie dzielimy po ``\\n`` -
    szukamy wzorca. ``yaw`` jest tylko przy ``PILOT``.
    """
    for match in MARKER_PATTERN.finditer(output):
        if match.group("marker") != marker:
            continue
        values = [float(match.group("x")), float(match.group("y")), float(match.group("z"))]
        if match.group("yaw") is not None:
            values.append(float(match.group("yaw")))
        return values
    raise AssertionError(f"brak znacznika {marker} w wyjściu:\n{output[:2000]}")


def sample_before_return_home(flight):
    """Ostatnia próbka telemetrii **przed** ``return_home`` (pozycja symulatora).

    Telemetria obejmuje cały lot (także powrót), więc bierzemy próbkę na chwilę
    przed zdarzeniem ``start: return_home`` - inaczej porównywalibyśmy pozycję
    pilota sprzed powrotu z pozycją symulatora po powrocie.
    """
    air = [s for s in flight.samples if s["z"] > 10]
    assert air, "brak telemetrii lotu"
    starts = [e for e in flight.events
              if e.get("command") == "annotate"
              and "start: return_home" in str(e.get("args"))]
    if not starts:
        return air[-1]
    moment = float(starts[0].get("t", 0.0))
    before = [s for s in air if s["t"] <= moment + 1e-6]
    return before[-1] if before else air[0]


def self_start_yaw(scenario: Scenario) -> float:
    """Kurs startowy w konwencji API (°, dodatni = w prawo), jak ``rotate_*``."""
    return float(scenario.start_yaw)


def check_scenario(scenario: Scenario) -> None:
    """Uruchom scenariusz i sprawdź kryteria z modułu (geometria, nie wynik)."""
    result = runner.run_script(scenario.script(), f"{scenario.name}.py")
    output = "".join(line if isinstance(line, str) else line.get("text", "")
                     for line in result.stdout or [])
    safety = [e for e in result.flight.errors
              if "SafetyError" in str(e.get("type", "")) + str(e.get("message", ""))]
    if result.status != "ok":
        # jedyny dozwolony błąd bez ``return_home``: złamanie limitu (SafetyError)
        assert safety, f"[{scenario.name}] nieoczekiwany błąd: " \
                       f"{[e['message'] for e in result.flight.errors][:2]}"
        return                                   # limity pilnowane - patrz test niżej

    simulator = sample_before_return_home(result.flight)
    pilot_pos = parse_marker(output, "PILOT")
    # ``pilot.position()`` jest w UKŁADZIE PILOTA (0 = kurs przy utworzeniu).
    # Gdy przed ``Pilot`` był ``rotate_*``, oś X pilota to nie oś X świata.
    # Zmierzone (seed: rotate_clockwise(90) + forward(100)): pilot (100, 0),
    # symulator (0, -100) - czyli obrót o **-yaw_api**: przy współrzędnych
    # „x przód, y lewo” skręt w prawo obraca układ przeciwnie do matematycznego.
    angle = -math.radians(self_start_yaw(scenario))
    px = pilot_pos[0] * math.cos(angle) - pilot_pos[1] * math.sin(angle)
    py = pilot_pos[0] * math.sin(angle) + pilot_pos[1] * math.cos(angle)
    sx, sy = simulator["x"], simulator["y"]
    distance = ((px - sx) ** 2 + (py - sy) ** 2) ** 0.5
    assert distance <= TOL_POSITION_CM, (
        f"[{scenario.name}] pilot {pilot_pos[0]:.1f},{pilot_pos[1]:.1f} "
        f"(w świecie {px:.1f},{py:.1f}) vs symulator {sx:.1f},{sy:.1f}: "
        f"{distance:.1f} cm > {TOL_POSITION_CM} cm")

    # kurs: telemetria trzyma kurs silnika (CCW+), ``pilot.yaw`` jest CCW+ w układzie
    # pilota; po dodaniu kursu startowego porównujemy oba w układzie świata
    if len(pilot_pos) > 3:
        heading_pilot = (pilot_pos[3] + self_start_yaw(scenario)) % 360.0
        heading_sim = (-simulator["yaw"]) % 360.0
        diff = abs(((heading_pilot - heading_sim + 180.0) % 360.0) - 180.0)
        assert diff <= TOL_HEADING_DEG, (
            f"[{scenario.name}] kurs pilota {heading_pilot:.1f}° vs "
            f"symulator {heading_sim:.1f}°: {diff:.1f}° > {TOL_HEADING_DEG}°")

    home = parse_marker(output, "DOM")
    back = (home[0] ** 2 + home[1] ** 2) ** 0.5
    assert back <= TOL_RETURN_HOME_CM, (
        f"[{scenario.name}] return_home: {back:.1f} cm od startu > {TOL_RETURN_HOME_CM} cm")


# --------------------------------------------------------------------- testy
@pytest.mark.parametrize("seed", FAST_SEEDS, ids=lambda s: f"seed{s}")
def test_random_flight_fast(seed):
    """Wariant szybki: 20 losowych sekwencji manewrów (zwykły zestaw testów)."""
    check_scenario(make_scenario(seed))


@pytest.mark.slow
@pytest.mark.parametrize("seed", SLOW_SEEDS, ids=lambda s: f"seed{s}")
def test_random_flight_full(seed):
    """Pełny wariant: 200 losowych sekwencji (marker ``slow``)."""
    check_scenario(make_scenario(seed))


def test_generator_is_reproducible():
    """Ten sam seed = ten sam scenariusz (inaczej nazwy przypadków nic nie znaczą)."""
    first = make_scenario(12345)
    second = make_scenario(12345)
    assert first.name == second.name
    assert [m.code for m in first.maneuvers] == [m.code for m in second.maneuvers]
    assert make_scenario(12346).name != first.name


def test_scenario_names_contain_seed():
    """Każdy przypadek ma ziarno w nazwie - błąd da się odtworzyć przez ``-k``."""
    for seed in (1, 7, 199):
        assert f"seed{seed}" in make_scenario(seed).name


def test_limits_never_broken_silently():
    """Przekroczenie limitu wysokości kończy się błędem, nie cichym lotem.

    Geometria: start na 80 cm (`takeoff`) + `move_up(40)` = 120 cm, limit
    pilota 150 cm - ``spiral(height=200)`` musi wyjść ponad limit i rzucić
    wyjątek (`PathError` z planera albo `SafetyError` z pilotа) **przed** lotem.
    """
    script = textwrap.dedent("""
        from djitellopy import Tello
        from dronemoves import Pilot

        tello = Tello()
        tello.connect()
        tello.takeoff()
        tello.move_up(40)
        pilot = Pilot(tello, speed=40, max_height_cm=150, max_radius_cm=500)
        with pilot:
            pilot.spiral(radius=60, height=200, turns=2)
        tello.land()
    """).strip() + "\n"
    result = runner.run_script(script, "limit.py")
    assert result.status == "error"
    messages = " ".join(str(e.get("message", "")) for e in result.flight.errors)
    assert "PathError" in messages or "SafetyError" in messages, messages[:400]
    assert "limit" in messages.lower(), messages[:400]


def random_route(rng: random.Random):
    """Losowa trasa planera (tryb „prosta”): 2-5 punktów w limicie zasięgu."""
    from app.features.route_planner.model import Route, Waypoint

    count = rng.randint(2, 5)
    points = []
    for _ in range(count):
        points.append(Waypoint(
            x=rng.choice([-200, -150, -100, -60, 0, 60, 100, 150, 200]),
            y=rng.choice([-200, -150, -100, -60, 0, 60, 100, 150, 200]),
            z=rng.choice([60, 80, 100, 120, 150]),
        ))
    return Route(points=points)


def _min_distance(samples, point) -> float:
    """Najmniejszy dystans 3D od próbki telemetrii do punktu trasy [cm]."""
    best = float("inf")
    for sample in samples:
        dx = sample["x"] - point[0]
        dy = sample["y"] - point[1]
        dz = sample["z"] - point[2]
        distance = (dx * dx + dy * dy + dz * dz) ** 0.5
        if distance < best:
            best = distance
    return best


def check_route(seed: int) -> None:
    """Wygeneruj trasę planera, przelot i sprawdź dystans do każdego punktu ≤ 5 cm."""
    from app.features.route_planner import codegen_simple

    rng = random.Random(seed)
    route = random_route(rng)
    source = codegen_simple.generate(route)
    result = runner.run_script(source, f"route-seed{seed}.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors][:2]
    samples = result.flight.samples
    assert samples
    for index, point in enumerate(route.waypoints(), start=1):
        distance = _min_distance(samples, point)
        assert distance <= 5.0, (
            f"[route-seed{seed}] punkt {index} {point}: tor przechodzi "
            f"{distance:.1f} cm od niego")


@pytest.mark.parametrize("seed", SLOW_ROUTE_SEEDS[:5], ids=lambda s: f"route-seed{s}")
def test_planner_route_fast(seed):
    """Wariant szybki: 5 losowych tras planera (zwykły zestaw testów)."""
    check_route(seed)


@pytest.mark.slow
@pytest.mark.parametrize("seed", SLOW_ROUTE_SEEDS, ids=lambda s: f"route-seed{s}")
def test_planner_route_full(seed):
    """Pełny wariant: 100 losowych tras planera (marker ``slow``)."""
    check_route(seed)
