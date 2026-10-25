"""Testy podpowiedzi edytora (``app/completions.py``) - generowane z kodu.

Nie sprawdzamy pełnej listy (zmieni się przy każdej nowej metodzie biblioteki),
tylko to, że podpowiedzi **powstają z introspekcji**: mają sygnatury i opisy
z docstringów, a nie z ręcznie wpisanej listy.
"""

from __future__ import annotations

from app import completions


def test_tello_methods_come_from_mock():
    """Metody mocka ``djitellopy`` trafiają do podpowiedzi z sygnaturą."""
    data = completions.build()
    labels = {item["label"] for item in data["tello"]}
    for expected in ("takeoff", "land", "move_forward", "rotate_clockwise",
                     "send_rc_control", "get_battery"):
        assert expected in labels, expected
    item = next(i for i in data["tello"] if i["label"] == "move_forward")
    assert "self" in item["detail"]              # sygnatura z inspect.signature
    assert item["type"] == "method"


def test_dronemoves_api_is_included():
    """``Pilot`` i funkcje biblioteki (np. ``safe_start``) są w podpowiedziach."""
    data = completions.build()
    pilot = {item["label"] for item in data["pilot"]}
    for expected in ("forward", "turn", "orbit", "figure_eight", "safe_land"):
        assert expected in pilot, expected
    module_items = {item["label"]: item for item in data["all"]
                    if item["type"] in ("function", "class")}
    assert "safe_start" in module_items
    assert "Pilot" in module_items
    assert module_items["Pilot"]["type"] == "class"


def test_docstring_becomes_info():
    """Pierwszy akapit docstringa trafia do ``info`` (podpowiedź z opisem)."""
    data = completions.build()
    described = [item for item in data["pilot"] if item["info"]]
    assert described, "brak opisów z docstringów w API biblioteki"
    assert all("\n" not in item["info"] for item in data["pilot"])


def test_all_list_has_unique_labels():
    """Lista ``all`` nie powtarza etykiet (ta sama nazwa w Tello i Pilot)."""
    data = completions.build()
    labels = [item["label"] for item in data["all"]]
    assert len(labels) == len(set(labels))
    assert len(data["all"]) >= max(len(data["tello"]), len(data["pilot"]))
