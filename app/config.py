"""Konfiguracja aplikacji - ``config.json`` w katalogu projektu.

Plik jest opcjonalny: bez niego działają wartości domyślne. Można w nim
wyłączyć całe funkcje (wtyczki), np. edytor przeszkód::

    {
      "features": {
        "obstacles": {"enabled": false}
      }
    }

Ścieżkę można nadpisać zmienną środowiskową ``DRONESIM_CONFIG_FILE``
(używane w testach).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from . import paths

#: domyślna nazwa pliku konfiguracji w katalogu projektu
CONFIG_NAME = "config.json"


def config_path() -> Path:
    """Ścieżka pliku konfiguracji (domyślnie ``<projekt>/config.json``)."""
    override = os.environ.get("DRONESIM_CONFIG_FILE")
    return Path(override) if override else paths.PROJECT_ROOT / CONFIG_NAME


def load() -> Dict[str, Any]:
    """Wczytaj konfigurację; brak lub błąd pliku = puste ustawienia."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def features() -> Dict[str, Any]:
    """Sekcja ``features`` konfiguracji (id funkcji -> ustawienia)."""
    value = load().get("features")
    return value if isinstance(value, dict) else {}


def feature_settings(feature_id: str) -> Dict[str, Any]:
    """Ustawienia jednej funkcji (pusty słownik, gdy brak)."""
    value = features().get(feature_id)
    return value if isinstance(value, dict) else {}
