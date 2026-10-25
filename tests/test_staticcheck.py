"""Testy statycznej analizy skryptu (``app/staticcheck.py``, ``ast`` bez wykonania).

Oczekiwania bierzemy z **limitów Tello** (20-500 cm, 1-360°, 10-100 cm/s),
a nie z zachowania analizatora: dla każdego przypadku wiemy z góry, czy
ostrzeżenie ma się pojawić i w której linii.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app import staticcheck

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = PROJECT_ROOT / "examples"


def _check(source: str):
    return staticcheck.check(textwrap.dedent(source))


def _lines(result):
    return [(item["line"], item["kind"]) for item in result["problems"]]


def test_syntax_error_has_line():
    """Błąd składni to ``error`` z numerem linii (skrypt się nie uruchomi)."""
    result = _check("tello = Tello()\nif True\n    pass\n")
    assert result["ok"] is False
    assert len(result["problems"]) == 1
    problem = result["problems"][0]
    assert problem["level"] == "error"
    assert problem["line"] == 2
    assert "składni" in problem["message"]


def test_move_out_of_range_high():
    """``move_forward(600)`` przekracza 500 cm - ostrzeżenie w tej linii."""
    result = _check("""\
        tello.takeoff()
        tello.move_forward(600)
        tello.land()
    """)
    assert result["ok"] is True                      # ostrzeżenie nie blokuje
    assert _lines(result) == [(2, "range")]
    assert "20-500" in result["problems"][0]["message"]


def test_move_out_of_range_low():
    """``move_left(10)`` jest poniżej 20 cm - Tello tego nie wykona."""
    result = _check("""\
        tello.takeoff()
        tello.move_left(10)
        tello.land()
    """)
    assert _lines(result) == [(2, "range")]


def test_move_in_range_is_clean():
    """Wartości w zakresie (20-500) nie dają ostrzeżeń."""
    result = _check("""\
        tello.takeoff()
        tello.move_forward(20)
        tello.move_back(500)
        tello.land()
    """)
    assert result["problems"] == []


def test_negative_move_uses_absolute_value():
    """``move_forward(-100)`` jest w zakresie (|−100| = 100)."""
    result = _check("""\
        tello.takeoff()
        tello.move_forward(-100)
        tello.land()
    """)
    assert result["problems"] == []


@pytest.mark.parametrize("call,expected", [
    ("rotate_clockwise(0)", True),           # 0° = brak ruchu, poza 1-360
    ("rotate_clockwise(90)", False),
    ("rotate_counter_clockwise(360)", False),
    ("rotate_counter_clockwise(400)", True),
    ("set_speed(5)", True),                  # 10-100
    ("set_speed(100)", False),
    ("set_speed(200)", True),
])
def test_rotate_and_speed_limits(call, expected):
    """Obroty 1-360° i prędkość 10-100 cm/s."""
    result = _check(f"tello.takeoff()\ntello.{call}\ntello.land()\n")
    assert bool(result["problems"]) is expected, result["problems"]


def test_go_xyz_speed_limits():
    """``go_xyz_speed``: każda osad do 500 cm i prędkość 10-100."""
    result = _check("""\
        tello.takeoff()
        tello.go_xyz_speed(600, 0, 0, 50)
        tello.go_xyz_speed(100, 0, 0, 500)
        tello.land()
    """)
    assert _lines(result) == [(2, "range"), (3, "range")]


def test_non_constant_argument_is_not_checked():
    """Zmienna zamiast stałej - analiza statyczna nie zgaduje wartości."""
    result = _check("""\
        distance = 600
        tello.takeoff()
        tello.move_forward(distance)
        tello.land()
    """)
    assert result["problems"] == []


def test_move_before_takeoff_is_reported():
    """Ruch przed ``takeoff()`` w prostym przepływie liniowym."""
    result = _check("""\
        tello.move_forward(100)
        tello.takeoff()
        tello.land()
    """)
    assert _lines(result) == [(1, "flow")]
    assert "przed takeoff" in result["problems"][0]["message"]


def test_move_before_takeoff_inside_if_is_not_reported():
    """W ``if``/``for`` kolejność zależy od danych - nie zgłaszamy."""
    result = _check("""\
        tello = Tello()
        if takeoff_first:
            tello.move_forward(100)
        tello.takeoff()
        tello.land()
    """)
    assert result["problems"] == []


def test_missing_land_is_reported():
    """Brak ``land()`` na końcu - dron zostanie w powietrzu."""
    result = _check("""\
        tello.takeoff()
        tello.move_forward(100)
    """)
    assert _lines(result) == [(2, "flow")]
    assert "Brak land()" in result["problems"][0]["message"]


def test_with_block_is_linear_flow():
    """``with`` i ``try`` mają kolejność liniową - analiza w nich wchodzi."""
    result = _check("""\
        tello = Tello()
        with Tello() as tello:
            tello.takeoff()
            tello.move_forward(600)
            tello.land()
    """)
    assert _lines(result) == [(4, "range")]


@pytest.mark.parametrize("name", ["basic_square.py", "climb_and_rotate.py"])
def test_examples_are_clean(name):
    """Przykłady z ``examples/`` nie mają błędów ani ostrzeżeń."""
    path = EXAMPLES / name
    assert path.exists(), name
    result = staticcheck.check(path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["problems"] == [], result["problems"]


def test_problems_sorted_by_line():
    """Problemy są posortowane po linii (kolejność w liście = kolejność w pliku)."""
    result = _check("""\
        tello.move_forward(600)
        tello.takeoff()
        tello.move_left(1)
    """)
    lines = [item["line"] for item in result["problems"]]
    assert lines == sorted(lines)
    assert len(lines) >= 3
