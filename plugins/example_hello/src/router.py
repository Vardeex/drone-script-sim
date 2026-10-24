"""Endpointy wtyczki ``example_hello`` (punkt rozszerzeń ``api``).

Router jest montowany pod ``api_prefix`` z manifestu - w tym wypadku
``/api/example_hello``. Wtyczka nie zna ścieżki montowania, więc endpointy
piszemy bez prefiksu (``@router.get("/hello")``).
"""

from __future__ import annotations

import datetime
from typing import Any, Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/hello")
def hello(name: str = "pilocie") -> Dict[str, Any]:
    """Powitanie z nazwą - wtyczka pokazuje, że API działa.

    :param name: kogo witać (parametr zapytania, domyślnie „pilocie”)
    """
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    safe = safe.strip()[:40] or "pilocie"
    return {
        "message": f"Cześć, {safe}! To odpowiedź wtyczki example_hello.",
        "plugin": "example_hello",
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/info")
def info() -> Dict[str, str]:
    """Krótki opis wtyczki (przydatny w testach i diagnostyce)."""
    return {
        "id": "example_hello",
        "version": "1.0.0",
        "note": "Wzór wtyczki zewnętrznej: panel + endpoint API.",
    }
