"""Wspólne elementy generatorów kodu (nagłówek, bateria, liczby)."""

from __future__ import annotations

from typing import List

from .model import Route, route_block


def num(value: float) -> str:
    """Liczba w kodzie: bez zbędnych zer (123, 123.5)."""
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def docstring(title: str, extra: List[str]) -> List[str]:
    """Docstring pliku (napis + dodatkowe linie opisu)."""
    return [f'"""{title}', ""] + extra + ['"""', ""]


def battery_check() -> List[str]:
    """Start przez ``safe_start``: preflight (bateria, temperatura, Wi-Fi) + takeoff.

    ``safe_start`` z biblioteki dronemoves sprawdza drona przed startem i rzuca
    ``PreflightError`` (np. bateria < 50 % albo dron w powietrzu), więc skrypt
    nie startuje w niebezpiecznych warunkach.
    """
    return [
        "    # 1. Preflight + start (bateria, temperatura, Wi-Fi, dron na ziemi)",
        "    safe_start(tello)",
    ]


def standard_header(route: Route, mode: str, title: str,
                    extra: List[str], imports: List[str]) -> List[str]:
    """Docstring + importy + blok-znacznik z trasą (wspólny początek pliku)."""
    return (docstring(title, extra) + imports + [""] + [route_block(route, mode), "",
                                                       ""])


def header(route: Route, mode: str, title: str) -> List[str]:
    """Nagłówek trybu płynnego: docstring, importy i blok-znacznik z trasą."""
    return standard_header(
        route, mode, title,
        ["Wygenerowane przez DroneSim - Planer trasy.", "",
         "Układ: x = przód, y = lewo, z = góra (cm), start w (0, 0, 0).",
         "Kurs nosa w konwencji Tello: dodatni = w prawo."],
        ["from djitellopy import Tello", "from dronemoves import Pilot",
         "from dronemoves.safety import safe_start"])
