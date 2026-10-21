"""Testy FIZYCZNE układu współrzędnych - niezależne od biblioteki dronemoves.

Sprawdzają, że symulator jest fizycznie spójny: obrót w prawo i ruch w prawo
idą na tę samą stronę (−y), a obrót w lewo na +y. Nie porównują niczego
z planerem, więc wyłapią błąd nawet gdyby biblioteka i symulator miały
identycznie odwróconą oś.

Układ projektu (README „Układ współrzędnych”): x = przód, y = LEWO, z = góra.
"""

from __future__ import annotations

import pytest

from app.adapters.tello.adapter import TelloController
from app.sim import core

#: strona „S” = prawa strona drona = ujemne y
RIGHT = -1
LEFT = +1


def _airborne() -> TelloController:
    ctrl = TelloController(core.Simulation())
    ctrl.connect()
    ctrl.takeoff()
    return ctrl


def _pos(ctrl: TelloController) -> tuple:
    return ctrl.sim.position


# ---------------------------------------------------------------- RC: w prawo
def test_rc_positive_left_right_moves_to_right_side():
    """``send_rc_control(+30, 0, 0, 0)`` przez 2 s przesuwa na stronę prawą (−y)."""
    ctrl = _airborne()
    ctrl.send_rc_control(30, 0, 0, 0)
    ctrl.rc_tick(2.0)
    x, y, _ = _pos(ctrl)
    assert y < -20, f"oczekiwano ruchu w prawo (−y), jest y={y:.1f}"
    assert abs(x) < 1.0, f"ruch w prawo nie może zmieniać x (x={x:.1f})"


def test_rc_negative_left_right_moves_to_left_side():
    ctrl = _airborne()
    ctrl.send_rc_control(-30, 0, 0, 0)
    ctrl.rc_tick(2.0)
    _, y, _ = _pos(ctrl)
    assert y > 20, f"oczekiwano ruchu w lewo (+y), jest y={y:.1f}"


# ------------------------------------------------- RC: skręt w prawo + przód
def test_rc_forward_with_clockwise_yaw_turns_to_the_right_side():
    """``(0, +30, 0, +30)``: obrót CW i tor na tę SAMĄ stronę (prawą, −y).

    To był błąd zgłoszony w 0.1.3: dron obracał się w prawo, ale leciał na +y
    (w lewo) - fizycznie niespójnie.
    """
    ctrl = _airborne()
    ctrl.send_rc_control(0, 30, 0, 30)
    ctrl.rc_tick(3.0)
    x, y, _ = _pos(ctrl)
    assert ctrl.get_yaw() > 0, f"yaw w get_yaw() musi rosnąć (CW+), jest {ctrl.get_yaw()}"
    assert y < 0, f"skręt w prawo przy locie do przodu musi iść na −y, jest y={y:.1f}"
    assert x > 20, f"dron powinien też lecieć do przodu, jest x={x:.1f}"


def test_rc_forward_with_counter_clockwise_yaw_turns_to_the_left_side():
    ctrl = _airborne()
    ctrl.send_rc_control(0, 30, 0, -30)
    ctrl.rc_tick(3.0)
    _, y, _ = _pos(ctrl)
    assert ctrl.get_yaw() < 0
    assert y > 0, f"skręt w lewo musi iść na +y, jest y={y:.1f}"


# ------------------------------------------- rotate_* + move_forward (kierunki)
def test_rotate_clockwise_then_forward_goes_to_right_side():
    """``rotate_clockwise(90)`` + ``move_forward(100)`` kończy na stronie prawej."""
    ctrl = _airborne()
    ctrl.rotate("rotate_clockwise", "cw", 90)
    ctrl.move("move_forward", "forward", 100)
    x, y, _ = _pos(ctrl)
    assert ctrl.get_yaw() == pytest.approx(90, abs=1)
    assert y < -90, f"po skręcie w prawo przód to −y, jest y={y:.1f}"
    assert abs(x) < 2.0


def test_rotate_counter_clockwise_then_forward_goes_to_left_side():
    ctrl = _airborne()
    ctrl.rotate("rotate_counter_clockwise", "ccw", 90)
    ctrl.move("move_forward", "forward", 100)
    x, y, _ = _pos(ctrl)
    assert ctrl.get_yaw() == pytest.approx(-90, abs=1)
    assert y > 90, f"po skręcie w lewo przód to +y, jest y={y:.1f}"


# ----------------------------------------------------------- spójność strony
def test_turning_right_is_the_same_side_as_moving_right():
    """Ruch w prawo i skręt w prawo muszą wskazywać TĘ SAMĄ stronę.

    Wykrywa każdą konfigurację, w której obrót i przesunięcie boczne mają
    odwrotne znaki (właśnie to zgłoszono jako błąd fizyczny).
    """
    straight = _airborne()
    straight.send_rc_control(30, 0, 0, 0)     # sam ruch w prawo
    straight.rc_tick(2.0)
    side_of_strafe = -1 if _pos(straight)[1] < 0 else +1

    turn = _airborne()
    turn.send_rc_control(0, 30, 0, 30)        # przód + skręt CW
    turn.rc_tick(3.0)
    side_of_turn = -1 if _pos(turn)[1] < 0 else +1

    assert side_of_strafe == side_of_turn == RIGHT, (
        f"ruch w prawo daje stronę {side_of_strafe:+d}, skręt w prawo {side_of_turn:+d} "
        "(muszą być takie same i równe -1 = prawa strona)")


# ------------------------------------- move_* / go_xyz_speed w układzie projektu
def test_move_directions_match_project_frame():
    """``move_left/right/forward/back/up`` w układzie x przód, y lewo, z góra."""
    # (komenda, kierunek, oś, oczekiwana wartość) - start po takeoff: (0, 0, 80)
    cases = [
        ("move_left", "left", 1, +100),
        ("move_right", "right", 1, -100),
        ("move_forward", "forward", 0, +100),
        ("move_back", "back", 0, -100),
        ("move_up", "up", 2, 180),
    ]
    for command, direction, axis, want in cases:
        ctrl = _airborne()
        ctrl.move(command, direction, 100)
        pos = _pos(ctrl)
        assert pos[axis] == pytest.approx(want, abs=1.0), (
            f"{command}: oś {axis} = {pos[axis]:.1f}, oczekiwano {want} (pełna pozycja {pos})")
        # pozostałe osie poziome bez zmian (start: x=0, y=0)
        if axis != 2:
            other = 0 if axis == 1 else 1
            assert pos[other] == pytest.approx(0.0, abs=1.0), (
                f"{command}: oś {other} nie powinna się zmienić (pozycja {pos})")


def test_moves_stay_in_drone_frame_after_clockwise_turn():
    """Po ``rotate_clockwise(90)`` przód drona to −y, a prawa strona to −x."""
    ctrl = _airborne()
    ctrl.rotate("rotate_clockwise", "cw", 90)

    forward = _airborne()
    forward.rotate("rotate_clockwise", "cw", 90)
    forward.move("move_forward", "forward", 100)
    fx, fy, _ = _pos(forward)
    assert fy < -90 and abs(fx) < 2.0, f"po skręcie w prawo przód to −y, jest ({fx:.1f}, {fy:.1f})"

    right = _airborne()
    right.rotate("rotate_clockwise", "cw", 90)
    right.move("move_right", "right", 100)
    rx, ry, _ = _pos(right)
    assert rx < -90 and abs(ry) < 2.0, f"po skręcie w prawo prawa strona to −x, jest ({rx:.1f}, {ry:.1f})"


def test_go_xyz_speed_uses_drone_frame_y_left():
    """``go_xyz_speed(y=+100)`` to ruch w LEWO (+y) - jak w API Tello."""
    ctrl = _airborne()
    ctrl.go_xyz_speed(0, 100, 0, 50)
    x, y, _ = _pos(ctrl)
    assert y > 90, f"go_xyz_speed(y=+100) ma iść na +y (lewo), jest y={y:.1f}"
    assert abs(x) < 2.0
