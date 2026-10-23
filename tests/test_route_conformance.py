"""Testy zgodności: wygenerowany skrypt faktycznie przelatuje przez punkty trasy.

Dla każdej trasy:

* każdy punkt jest w odległości <= 5 cm od toru lotu (tryb „prosta”)
  i <= 15 cm (tryb „płynna”, wygładzanie spline),
* punkty są odwiedzane w kolejności trasy,
* kurs nosa w punktach ze stałym kursem jest zgodny w granicach ±5°.

Oczekiwane wartości wynikają z samej trasy (współrzędne w punktach), nie
z wyniku programu.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.features.route_planner import codegen_simple, codegen_smooth
from app.features.route_planner.model import Route, Waypoint
from app.server import app
from tests.route_helpers import (
    is_monotonic, min_distance, run_script, visit_times, yaw_error,
)

LIMITS = {"simple": 5.0, "smooth": 15.0}

# Tryb „płynna” (eksperymentalny) ma udokumentowane odchylenia; trasy poniżej
# przekraczają 15 cm z powodu KNOWN_ISSUES KI-1 (path nie realizuje kursu
# zaplanowanego na starcie manewru). Test NIE zmienia oczekiwań - jest xfail
# z odnośnikiem do KNOWN_ISSUES.md, a UI pokazuje ostrzeżenie z odchyleniem.
# Tryb „płynna” (eksperymentalny) ma udokumentowane odchylenia; trasy poniżej
# nie spełniają jeszcze oczekiwań (KNOWN_ISSUES.md). Test NIE zmienia oczekiwań -
# jest xfail z odnośnikiem, a UI pokazuje ostrzeżenie z odchyleniem.
SMOOTH_KNOWN_ISSUE = {
    "obroty": "KI-4: kurs nosa po obrocie w punkcie (94° zamiast 270°)",
    "dluga 600 cm": "tryb „płynna” nie obsługuje powrotu do startu (RouteError)",
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------- trasy
def square_route() -> Route:
    """Kwadrat 100 x 100 cm na wysokości 80 cm (powrót do punktu startu)."""
    return Route(points=[Waypoint(100, 0, 80), Waypoint(100, 100, 80),
                         Waypoint(0, 100, 80), Waypoint(0, 0, 80)])


def turns_route() -> Route:
    """Trasa z obrotami i zmianą wysokości: w górę, w bok, w dół i obrót w punkcie."""
    return Route(points=[Waypoint(150, 0, 120),
                         Waypoint(150, 120, 120),
                         Waypoint(60, 120, 60, heading="fixed", yaw_deg=270)])


def detour_route(obstacles: list) -> Route:
    """Trasa wokół przeszkody z „Toru przeszkód” (punkt po prawej stronie ściany)."""
    return Route(points=[Waypoint(120, 0, 100), Waypoint(120, 150, 100),
                         Waypoint(300, 150, 100)])


def long_route() -> Route:
    """Odcinek 600 cm (limit Tello 500 cm) + powrót do startu."""
    return Route(points=[Waypoint(600, 0, 80), Waypoint(600, 100, 80)],
                 return_home=True)


def behind_route() -> Route:
    """Punkt za plecami drona (y ujemne wymaga obrotu przed lotem)."""
    return Route(points=[Waypoint(0, -120, 80), Waypoint(80, -120, 80)])


def all_routes() -> list:
    path = Path(__file__).resolve().parent.parent / "scenes" / "obstacle_course.json"
    import json

    scene = json.loads(path.read_text(encoding="utf-8"))
    return [("kwadrat", square_route()), ("obroty", turns_route()),
            ("wokol przeszkody", detour_route(scene.get("obstacles") or [])),
            ("dluga 600 cm", long_route()), ("za plecami", behind_route())]


def expected_fixed_yaw(route: Route) -> dict:
    """Stałe kursy nosa w punktach (oczekiwane wprost z trasy)."""
    return {index + 1: point.yaw_deg for index, point in enumerate(route.points)
            if point.heading == "fixed"}


# --------------------------------------------------------------------- testy
@pytest.mark.parametrize("mode", ["simple", "smooth"])
@pytest.mark.parametrize("name,route", all_routes(), ids=[n for n, _ in all_routes()])
def test_generated_script_visits_every_point(request, client, mode: str, name: str,
                                             route: Route):
    """Skrypt przelatuje przez wszystkie punkty: blisko toru i w kolejności."""
    if mode == "smooth" and name in SMOOTH_KNOWN_ISSUE:
        reason = SMOOTH_KNOWN_ISSUE[name]
        request.node.add_marker(pytest.mark.xfail(
            reason=f"KNOWN_ISSUES.md (KI-1): {reason}", strict=True))
    generator = codegen_simple.generate if mode == "simple" else codegen_smooth.generate
    source = generator(route)
    flight = run(client, source, mode)
    try:
        samples = flight["samples"]
        assert samples, flight.get("errors")
        limit = LIMITS[mode]
        for index, point in enumerate(route.waypoints(), start=1):
            distance = min_distance(samples, point)
            assert distance <= limit, (f"tryb {mode}, trasa {name}: punkt {index} "
                                       f"{point} - tor przechodzi {distance:.1f} cm od niego")
        order = visit_times(samples, route.waypoints())
        assert is_monotonic(order), (f"tryb {mode}, trasa {name}: punkty odwiedzone "
                                     f"poza kolejnością: {order}")
        # kurs nosa sprawdzamy po obrocie wykonanym w punkcie (nie w chwili
        # dojazdu). Telemetria trzyma kurs silnika (dodatni = w lewo, CCW),
        # a trasa i `get_yaw()` - kurs API (dodatni = w prawo), więc
        # porównujemy `-yaw_z_telemetrii` z kursem z trasy (adapter.py: get_yaw = -sim.yaw).
        for number, yaw in expected_fixed_yaw(route).items():
            arrived = order[number - 1]
            assert arrived < math.inf, f"punkt {number} nieosiągnięty"
            window = [s for s in samples if arrived - 0.1 <= s["t"] <= arrived + 4.0]
            assert window, f"brak próbek po dojeździe do punktu {number}"
            best = min(yaw_error(-s["yaw"], yaw) for s in window)
            assert best <= 5.0, (
                f"tryb {mode}, trasa {name}: punkt {number} miał kurs {yaw}°, "
                f"a dron najbliżej {best:.1f}°")
    finally:
        client.delete(f"/api/flights/{flight['id']}")


def run(client, source: str, mode: str) -> dict:
    """Uruchomienie skryptu (``POST /api/run``) i zwrócenie lotu."""
    return run_script(client, source, f"trasa_{mode}.py")
