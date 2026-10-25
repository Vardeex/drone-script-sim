"""Statyczna analiza skryptu przed uruchomieniem (``ast``, bez wykonywania kodu).

Sprawdzenia (wszystkie **nie blokują** uruchomienia - to podpowiedzi w edytorze):

* błąd składni -> ``level: error`` z numerem linii (skrypt się nie uruchomi),
* argumenty **stałe** poza zakresem Tello: ``move_*`` 20-500 cm,
  ``rotate_*`` 1-360°, ``set_speed`` 10-100 cm/s, ``go_xyz_speed``
  ``|x|,|y|,|z| <= 500`` i prędkość 10-100,
* ruch przed ``takeoff()`` w prostym przepływie liniowym (bez wchodzenia
  w ``if``/``for``/``while`` - tam kolejność może zależeć od danych),
* brak ``land()`` na końcu skryptu.

Zakresy bierzemy z ``app.adapters.tello.limits`` (jedno źródło prawdy dla
adaptera) - zmiana limitu nie wymaga zmiany analizatora.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Optional

#: komendy ruchu (zakres odległości w cm)
MOVE_CALLS = ("move_forward", "move_back", "move_left", "move_right",
              "move_up", "move_down")
#: komendy obrotu (zakres kąta w stopniach)
ROTATE_CALLS = ("rotate_clockwise", "rotate_counter_clockwise")
#: komendy wymagające drona w powietrzu
AIRBORNE_CALLS = ("takeoff",) + MOVE_CALLS + ROTATE_CALLS + (
    "go_xyz_speed", "go_xyz_speed_mid")


def _limits() -> Dict[str, float]:
    """Zakresy z adaptera Tello (z bezpiecznym fallbackiem)."""
    try:
        from .adapters.tello.limits import LIMITS

        return {
            "move_min": float(LIMITS.move_min_cm),
            "move_max": float(LIMITS.move_max_cm),
            "rotate_min": float(LIMITS.rotate_min_deg),
            "rotate_max": float(LIMITS.rotate_max_deg),
            "speed_min": float(LIMITS.speed_min),
            "speed_max": float(LIMITS.speed_max),
        }
    except Exception:                     # noqa: BLE001 - brak adaptera nie psuje analizy
        return {"move_min": 20.0, "move_max": 500.0, "rotate_min": 1.0,
                "rotate_max": 360.0, "speed_min": 10.0, "speed_max": 100.0}


def _problem(level: str, message: str, line: Optional[int],
             kind: str = "value") -> Dict[str, Any]:
    return {"level": level, "message": message, "line": line, "kind": kind}


def _call_name(node: ast.Call) -> Optional[str]:
    """Nazwa wywołania: ``tello.move_forward`` -> ``move_forward``."""
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return None


def _constant(node: ast.AST) -> Optional[float]:
    """Wartość argumentu, jeśli jest **stałą liczbową** (inaczej ``None``)."""
    value: Any = None
    if isinstance(node, ast.Constant):
        value = node.value
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) \
            and isinstance(node.operand, ast.Constant):
        operand = node.operand.value
        value = -operand if isinstance(operand, (int, float)) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _num(value: float) -> str:
    return str(int(value)) if abs(value - round(value)) < 1e-9 else f"{value:g}"


def _check_ranges(tree: ast.AST, limits: Dict[str, float]) -> List[Dict[str, Any]]:
    """Sprawdź stałe argumenty komend Tello (zakresy z adaptera)."""
    problems: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        if name in MOVE_CALLS and node.args:
            value = _constant(node.args[0])
            low, high = limits["move_min"], limits["move_max"]
            if value is not None and not (low <= abs(value) <= high):
                problems.append(_problem(
                    "warning",
                    f"{name}({_num(abs(value))}): odległość poza zakresem Tello "
                    f"{_num(low)}-{_num(high)} cm", node.lineno, "range"))
        elif name in ROTATE_CALLS and node.args:
            value = _constant(node.args[0])
            low, high = limits["rotate_min"], limits["rotate_max"]
            if value is not None and not (low <= abs(value) <= high):
                problems.append(_problem(
                    "warning",
                    f"{name}({_num(abs(value))}): kąt poza zakresem Tello "
                    f"{_num(low)}-{_num(high)}°", node.lineno, "range"))
        elif name == "set_speed" and node.args:
            value = _constant(node.args[0])
            low, high = limits["speed_min"], limits["speed_max"]
            if value is not None and not (low <= value <= high):
                problems.append(_problem(
                    "warning",
                    f"set_speed({_num(value)}): prędkość poza zakresem Tello "
                    f"{_num(low)}-{_num(high)} cm/s", node.lineno, "range"))
        elif name == "go_xyz_speed":
            for index, axis in enumerate(("x", "y", "z")):
                if len(node.args) <= index:
                    continue
                value = _constant(node.args[index])
                if value is not None and abs(value) > limits["move_max"]:
                    problems.append(_problem(
                        "warning",
                        f"go_xyz_speed({axis}={_num(value)}): przekracza limit "
                        f"{_num(limits['move_max'])} cm", node.lineno, "range"))
            if len(node.args) > 3:
                value = _constant(node.args[3])
                low, high = limits["speed_min"], limits["speed_max"]
                if value is not None and not (low <= value <= high):
                    problems.append(_problem(
                        "warning",
                        f"go_xyz_speed(speed={_num(value)}): prędkość poza zakresem "
                        f"Tello {_num(low)}-{_num(high)} cm/s", node.lineno, "range"))
    return problems


def _linear_calls(body: List[ast.stmt]) -> List[ast.Call]:
    """Wywołania w **prostym przepływie liniowym** (kolejność wykonania).

    Wchodzimy do ``try``/``with``/``finally`` (tam kolejność jest liniowa),
    ale **nie** do ``if``/``for``/``while``/``def`` - w tych miejscach kolejność
    zależy od danych i analiza liniowa dałaby fałszywe ostrzeżenia.
    """
    calls: List[ast.Call] = []
    for statement in body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            calls.append(statement.value)
        elif isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
            calls.append(statement.value)
        elif isinstance(statement, (ast.Try, ast.With)):
            calls.extend(_linear_calls(statement.body))
            calls.extend(_linear_calls(getattr(statement, "finalbody", []) or []))
            for handler in getattr(statement, "handlers", []) or []:
                calls.extend(_linear_calls(handler.body))
    return calls


def _check_flow(tree: ast.Module) -> List[Dict[str, Any]]:
    """Ruch przed ``takeoff()`` i brak ``land()`` na końcu."""
    problems: List[Dict[str, Any]] = []
    calls = _linear_calls(tree.body)
    took_off = False
    for call in calls:
        name = _call_name(call)
        if name == "takeoff":
            took_off = True
            continue
        if name in AIRBORNE_CALLS and not took_off:
            problems.append(_problem(
                "warning",
                f"{name}() przed takeoff() - dron jeszcze nie jest w powietrzu "
                "(Tello odrzuci tę komendę)", call.lineno, "flow"))
            break
    has_land = any(_call_name(call) == "land" for call in calls)
    if calls and not has_land:
        last = calls[-1]
        problems.append(_problem(
            "warning", "Brak land() na końcu - dron zostanie w powietrzu",
            last.lineno, "flow"))
    return problems


def check(source: str) -> Dict[str, Any]:
    """Sprawdź skrypt i zwróć ``{problems, ok, error}``.

    :returns: ``problems`` - lista ``{level, message, line, kind}`` posortowana
        po linii; ``ok`` - brak problemów poziomu ``error`` (skrypt się uruchomi).
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError as exc:
        line = exc.lineno or 1
        message = f"Błąd składni: {exc.msg}"
        return {"problems": [_problem("error", message, line, "syntax")],
                "ok": False, "error": message}
    limits = _limits()
    problems = _check_ranges(tree, limits) + _check_flow(tree)
    problems.sort(key=lambda item: (item["line"] or 0, item["message"]))
    return {"problems": problems,
            "ok": not any(item["level"] == "error" for item in problems),
            "error": None}
