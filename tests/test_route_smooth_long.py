"""Testy trybu „płynna” dla długich tras (Zadanie: dluga 600 bez xfail).

Sedno: ``Pilot.path`` dostaje punkty **względne**, a jego ``max_radius_cm``
liczy oddalenie **od startu pilota**. Trasa z punktem 600 cm od startu łamała
oba ograniczenia, a ``return_home`` był w ogóle odrzucany. Generowany kod dzieli
długie odcinki na kawałki ≤ 400 cm i wywołuje ``pilot.return_home()``.
"""

from __future__ import annotations

import math

import pytest

from app import runner
from app.features.route_planner import codegen_smooth
from app.features.route_planner.model import TAKEOFF_HEIGHT_CM, Route, Waypoint


def long_route() -> Route:
    """Trasa z testu konformacji: odcinek 600 cm (limit Tello 500) + powrót."""
    return Route(points=[Waypoint(600, 0, 80), Waypoint(600, 100, 80)],
                 return_home=True)


def test_long_route_generates_and_flies():
    """Trasa 600 cm z powrotem generuje skrypt, który kończy się bez błędu."""
    source = codegen_smooth.generate(long_route())
    assert "return_home()" in source
    result = runner.run_script(source, "long.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors][:2]


def test_long_route_visits_points_within_15cm():
    """Każdy punkt trasy przeleciany w odległości ≤ 15 cm (oczekiwanie z zadania)."""
    source = codegen_smooth.generate(long_route())
    result = runner.run_script(source, "long.py")
    assert result.status == "ok"
    for point in long_route().waypoints():
        best = min(math.dist((s["x"], s["y"], s["z"]), point)
                   for s in result.flight.samples)
        assert best <= 15.0, f"punkt {point}: {best:.1f} cm"


def test_long_route_returns_home_within_10cm():
    """``return_home`` w trybie płynnym wraca ≤ 10 cm od startu."""
    source = codegen_smooth.generate(long_route())
    result = runner.run_script(source, "long.py")
    air = [s for s in result.flight.samples if s["z"] > 10]
    last = air[-1]
    distance = math.hypot(last["x"], last["y"])
    assert distance <= 10.0, f"{distance:.1f} cm od startu"


def test_long_legs_are_split_into_short_pieces():
    """Odcinek 600 cm dzielony na kawałki ≤ MAX_PATH_LEG_CM (2 części po 300 cm)."""
    route = Route(points=[Waypoint(600, 0, 80)])
    pieces = codegen_smooth._split_legs(route.waypoints(), (0.0, 0.0, TAKEOFF_HEIGHT_CM))
    assert len(pieces) == 1
    points = pieces[0]
    assert len(points) == 2
    assert math.dist(points[0][:2], (0.0, 0.0)) == pytest.approx(300.0)
    assert math.dist(points[1][:2], (0.0, 0.0)) == pytest.approx(600.0)


def test_short_route_is_unchanged():
    """Krótkie odcinki zostają w jednym ``path`` - generowany kod bez zmian.

    Regresja złapana w trakcie: dzielenie trasy przy każdym punkcie psuło
    „kwadrat” (kolejne wywołania liczyły offset od punktu pośredniego).
    """
    route = Route(points=[Waypoint(100, 0, 80), Waypoint(100, 100, 80),
                          Waypoint(0, 100, 80), Waypoint(0, 0, 80)])
    source = codegen_smooth.generate(route)
    assert source.count("pilot.path(") == 1
    assert "pilot.path([(100, 0, 0), (100, 100, 0), (0, 100, 0), (0, 0, 0)]" in source


def test_pilot_radius_covers_farthest_point():
    """``max_radius_cm`` pilota pokrywa najdalszy punkt trasy (z zapasem)."""
    source = codegen_smooth.generate(long_route())
    radius = math.hypot(600, 100)
    assert f"max_radius_cm={math.ceil(radius * 1.1)}" in source
