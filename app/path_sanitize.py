"""Sanityzacja ścieżek w tekście (stdout/stderr, tracebacki, zapisy lotów).

Cel: zapis lotu i UI nie mogą pokazywać prywatnych ścieżek użytkownika
(katalog domowy, katalog tymczasowy systemu). Zasady:

* **ścieżka wewnątrz projektu** -> ścieżka **względna** z separatorami ``/``
  (np. ``app/adapters/tello/djitellopy/__init__.py``),
* **ścieżka spoza projektu** -> **sama nazwa pliku** (np. ``script.py``).

Działa dla obu stylów zapisu: Windows (``C:\\Users\\...``, ``C:/Users/...``)
i POSIX (``/home/...``, ``/tmp/...``, ``/Users/...``). Wcześniejsza wersja
opierała się na jednym wyrażeniu regularnym, które na Linuksie sklejało
ścieżki *wewnątrz* projektu (``app/adapters/.../__init__.py`` stawało się
``app__init__.py``) - stąd KI-6.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

#: ścieżka bezwzględna: Windows (``C:\``, ``C:/``, ``\\serwer\udzial``) albo POSIX (``/``)
#: Uwaga: ``/`` musi być na **początku** ścieżki - inaczej łapałby ukośniki
#: w ścieżkach względnych (``app/adapters/.../__init__.py`` -> ``app__init__.py``).
_ABSOLUTE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\s\"'<>|*?\\/]+[\\/]|(?<![\w./\\-])/)"
    r"(?:[^\s\"'<>|*?:\\/]+[\\/])*[^\s\"'<>|*?:\\/]*"
)

#: końcówka, która wygląda jak nazwa pliku z rozszerzeniem
_FILE_LIKE = re.compile(r"[^\\/]+\.[A-Za-z][A-Za-z0-9_]{0,9}$")


def _normalize(text: str) -> str:
    """Ujednolić separatory i usunąć cudzysłowy otaczające ścieżkę."""
    return text.strip().strip("\"'").replace("\\", "/")


def _is_inside(normalized: str, project: str) -> bool:
    """Czy ścieżka (już z ``/``) leży w katalogu projektu (``project`` też z ``/``)."""
    if not project:
        return False
    return normalized == project or normalized.startswith(project + "/")


def sanitize_path(raw: str, project_root: Optional[Path] = None) -> str:
    """Zamień jedną ścieżkę według zasad opisanych w docstringu modułu.

    :param raw: ścieżka tak, jak pojawiła się w tekście (może mieć cudzysłowy)
    :param project_root: katalog projektu; domyślnie ``app.paths.PROJECT_ROOT``
    """
    normalized = _normalize(raw)
    if project_root is None:
        from . import paths

        project_root = paths.PROJECT_ROOT
    project = _normalize(str(project_root)).rstrip("/")
    if _is_inside(normalized, project):
        relative = normalized[len(project):].lstrip("/")
        return relative or "."
    return normalized.rsplit("/", 1)[-1]


def sanitize_text(text: str, project_root: Optional[Path] = None) -> str:
    """Zamień wszystkie ścieżki w tekście (zachowując resztę znaków).

    Ścieżki wewnątrz projektu stają się względne (``app/...``), spoza projektu -
    samą nazwą pliku. Ścieżki bez rozszerzenia (np. ``/usr/lib/python3.11``)
    zostawiamy bez zmian tylko wtedy, gdy nie wskazują na plik użytkownika -
    w praktyce tracebacki zawierają pliki ``.py``, więc wymagamy rozszerzenia.
    """
    if not text:
        return text
    if project_root is None:
        from . import paths

        project_root = paths.PROJECT_ROOT

    def replace(match: "re.Match[str]") -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,:;)":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        if not _FILE_LIKE.search(_normalize(raw)):
            return match.group(0)
        return sanitize_path(raw, project_root) + trailing

    return _ABSOLUTE_PATH.sub(replace, text)
