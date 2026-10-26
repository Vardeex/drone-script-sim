"""Edycja wydania aplikacji: standardowa albo ``for_potatoes``.

To **nie jest** osobna wersja ani osobna gałąź - ten sam kod w innym opakowaniu.
Plik ``edition.json`` w katalogu programu mówi, którą edycję zbudowano::

    {"edition": "for_potatoes"}

Bez pliku (albo przy nieznanej wartości) działa edycja standardowa, czyli
zachowanie identyczne jak dotąd - wszystkie dotychczasowe testy przechodzą bez
zmian.

Edycja ``for_potatoes`` (słabe komputery): startuje w trybie lekkim bez pytania
i bez pomiaru FPS, a mało przydatne dodatki są domyślnie wyłączone (można je
włączyć w ustawieniach).

Ścieżkę pliku można nadpisać zmienną ``DRONESIM_EDITION_FILE`` (testy).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from . import __version__, paths

STANDARD = "standard"
FOR_POTATOES = "for_potatoes"
EDITION_FILE = "edition.json"

#: nazwy wyświetlane (nagłówek, „O programie”, instalator)
DISPLAY_NAMES = {
    STANDARD: "",
    FOR_POTATOES: "for_potatoes",
}


def edition_path() -> Path:
    """Ścieżka pliku ``edition.json`` (domyślnie w katalogu programu)."""
    override = os.environ.get("DRONESIM_EDITION_FILE")
    return Path(override) if override else paths.PROJECT_ROOT / EDITION_FILE


def read_edition() -> str:
    """Nazwa edycji z pliku; brak pliku lub błąd = edycja standardowa."""
    path = edition_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return STANDARD
    value = str(data.get("edition", "")).strip().lower() if isinstance(data, dict) else ""
    return FOR_POTATOES if value == FOR_POTATOES else STANDARD


def is_potatoes() -> bool:
    return read_edition() == FOR_POTATOES


def info() -> Dict[str, Any]:
    """Opis edycji dla interfejsu (``/api/edition``)."""
    edition = read_edition()
    suffix = DISPLAY_NAMES.get(edition, "")
    return {
        "edition": edition,
        "display_name": f"{__version__} {suffix}".strip(),
        "app_version": __version__,
        # edycja for_potatoes startuje w trybie lekkim (bez pomiaru FPS)
        "lite_default": edition == FOR_POTATOES,
        "features": {
            # dodatki wyłączone domyślnie w for_potatoes (włączalne w UI)
            "fpv": edition != FOR_POTATOES,
            "realism": edition != FOR_POTATOES,
            "plan_line": edition != FOR_POTATOES,
            "example_plugin": edition != FOR_POTATOES,
        },
    }
