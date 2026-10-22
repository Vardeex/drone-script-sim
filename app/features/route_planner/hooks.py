"""Punkt rozszerzeń nr 2 (hook „po zapisaniu lotu”) dla planera trasy.

Rdzeń zapisuje lot i woła ``on_flight_saved(payload, options)``. Planer
dopisuje do lotu trasę z opcji uruchomienia (``options.route_planner.route``)
i znacznik ``payload["route"]``, żeby po wczytaniu lotu z historii można było
odtworzyć trasę w edytorze. Wyjątek nie psuje zapisu lotu.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from .model import Route, RouteError


def on_flight_saved(payload: Dict[str, Any],
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dopisz trasę do zapisu lotu (klucz ``route``)."""
    opts = (options or {}).get("route_planner") or {}
    raw = opts.get("route")
    if not raw:
        # lot bez trasy planera: UI dostaje wyraźny sygnał „brak trasy”
        payload.setdefault("route", None)
        return payload
    try:
        route = Route.from_dict(raw)
    except RouteError as exc:
        print(f"[route_planner] trasa w locie niepoprawna: {exc}", file=sys.stderr)
        payload["route"] = None
        return payload
    payload["route"] = route.as_dict()
    return payload


def register(storage: Any) -> None:
    """Rejestracja hooka w rdzeniu (idempotentna)."""
    storage.register_post_save_hook(on_flight_saved)
