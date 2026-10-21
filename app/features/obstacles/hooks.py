"""Punkt rozszerzeń nr 2: „po symulacji przeanalizuj lot”.

Rdzeń zapisuje lot (``app.storage.save``) i woła ``on_flight_saved``. Ten
moduł nie importuje rdzenia - dostaje gotowy słownik lotu i może go wzbogacić
(np. dopisać ``payload["obstacles"]``). Wyjątek w funkcji nie psuje zapisu
lotu: analiza jest tylko dodatkiem.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional


def on_flight_saved(payload: Dict[str, Any],
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dopisz do lotu raport kolizji ze sceną przeszkód zapisaną w locie.

    :param payload: zapis lotu (format ``storage.flight_to_dict``) - modyfikowany
    :param options: ustawienia z żądania uruchomienia, klucz ``obstacles``:
        ``{"scene": {...}, "margin_cm": 20}``
    """
    opts = (options or {}).get("obstacles") or {}
    scene = opts.get("scene") or payload.get("scene")
    if not scene:
        payload.setdefault("obstacles", None)
        return payload
    margin = opts.get("margin_cm")
    payload["scene"] = scene
    try:
        from .collisions import DEFAULT_MARGIN, analyse_flight

        report = analyse_flight(
            payload.get("samples") or [],
            payload.get("events") or [],
            scene,
            margin=DEFAULT_MARGIN if margin is None else float(margin),
        )
    except Exception as exc:  # pragma: no cover - analiza nie może psuć zapisu
        print(f"[obstacles] analiza lotu nieudana: {type(exc).__name__}: {exc}", file=sys.stderr)
        payload["obstacles"] = {"error": f"{type(exc).__name__}: {exc}", "stats": {}}
        return payload
    payload["obstacles"] = report
    return payload


def attach_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Przy wczytywaniu lotu: dolicz raport, jeśli starszy lot go nie ma."""
    if "obstacles" in payload:
        return payload
    if payload.get("scene"):
        on_flight_saved(payload)
    return payload


def register(storage: Any) -> None:
    """Punkt rejestracji: rdzeń podaje własny moduł ``storage``.

    Nie importujemy rdzenia - dostajemy go w argumencie, więc funkcja pozostaje
    niezależna (można ją usunąć bez ruszania reszty aplikacji).
    """
    storage.register_post_save_hook(on_flight_saved)
