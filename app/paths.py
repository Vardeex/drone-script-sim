"""Ścieżki projektu - wszystkie liczone względem katalogu repozytorium.

Nie używamy ścieżek bezwzględnych, aby projekt można było sklonować w dowolne
miejsce (na Windows, macOS i Linux).
"""

from __future__ import annotations

import os
from pathlib import Path

#: katalog najwyższego poziomu projektu (zawiera ``app/``, ``examples/`` itd.)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

APP_DIR: Path = PROJECT_ROOT / "app"
STATIC_DIR: Path = APP_DIR / "static"
ADAPTERS_DIR: Path = APP_DIR / "adapters"
TEMPLATES_DIR: Path = APP_DIR / "templates"

FLIGHTS_DIR: Path = PROJECT_ROOT / "flights"
EXAMPLES_DIR: Path = PROJECT_ROOT / "examples"
TESTS_DIR: Path = PROJECT_ROOT / "tests"
UPLOADS_DIR: Path = FLIGHTS_DIR / "_uploads"

IS_WINDOWS: bool = os.name == "nt"
VENV_DIR: Path = PROJECT_ROOT / ".venv"
VENV_PYTHON: Path = VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def ensure_dirs() -> None:
    """Utworz katalogi runtime, jeśli nie istnieją."""
    for path in (FLIGHTS_DIR, UPLOADS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def cleanup_work_dirs(max_age_seconds: float = 3600.0) -> int:
    """Usuń stare katalogi robocze uruchomień (np. po zabitym procesie).

    Zwraca liczbę usuniętych katalogów. Młodsze niż ``max_age_seconds``
    zostają - mogą należeć do trwających uruchomień.
    """
    import shutil
    import time

    if not UPLOADS_DIR.exists():
        return 0
    removed = 0
    now = time.time()
    for child in UPLOADS_DIR.iterdir():
        if not child.is_dir():
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:
            continue
        if age > max_age_seconds:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def is_within(child: Path, parent: Path) -> bool:
    """Czy ``child`` leży w ``parent`` (po rozwiązywaniu ścieżek)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
