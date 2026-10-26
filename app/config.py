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
    """Ścieżka pliku konfiguracji.

    Kolejność: ``DRONESIM_CONFIG_FILE`` (testy) -> ``<dane>/config.json``
    (katalog projektu albo ``%LOCALAPPDATA%\\DroneSim`` w wersji instalowanej).
    """
    override = os.environ.get("DRONESIM_CONFIG_FILE")
    return Path(override) if override else paths.CONFIG_FILE


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


def save(data: Dict[str, Any]) -> None:
    """Zapisz konfigurację do pliku (UTF-8, z wcięciem - czytelna dla człowieka)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def set_feature_enabled(feature_id: str, enabled: bool) -> Dict[str, Any]:
    """Zapisz stan wtyczki w ``config.json`` (reszta konfiguracji bez zmian).

    Zwraca całą konfigurację po zmianie. Pozostałe klucze ustawień wtyczki
    (np. ``scene``) zostają - nadpisujemy tylko ``enabled``.
    """
    data = load()
    section = data.get("features")
    if not isinstance(section, dict):
        section = {}
        data["features"] = section
    current = section.get(feature_id)
    if isinstance(current, dict):
        current = {**current, "enabled": bool(enabled)}
    else:
        current = {"enabled": bool(enabled)}
    section[feature_id] = current
    save(data)
    return data
