"""Wspólne pomocniki skryptów wydania (wersja aplikacji, konsola UTF-8, uruchamianie).

Trzymane osobno, żeby ``build_exe.py``, ``build_installer.py`` i ``build_portable.py``
nie powielały tych samych trzech rzeczy. Skrypty można uruchamiać zarówno jako
moduł (``python -m release_tools.build_exe``), jak i bezpośrednio
(``python release_tools/build_exe.py``).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent


def utf8_console() -> None:
    """Wymuś UTF-8 na ``stdout``/``stderr`` (konsola Windows to cp1252).

    Bez tego polskie komunikaty kończą się ``UnicodeEncodeError`` - m.in. na
    runnerze GitHub Actions. Wszystko w ``try/except``: starsze Pythony
    i podmienione strumienie (np. w testach) nie mają ``reconfigure``.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def app_version() -> str:
    """Wersja aplikacji z ``app/__init__.py`` (bez importu aplikacji)."""
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("nie znaleziono __version__ w app/__init__.py")
    return match.group(1)


def version_tuple(version: str) -> tuple:
    """``"0.4.0"`` -> ``(0, 4, 0, 0)`` (cztery liczby dla metadanych pliku EXE)."""
    parts = [int(part) for part in re.findall(r"\d+", version)][:4]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def run(command: Sequence[str], cwd: Optional[Path] = None,
        timeout: int = 1800) -> subprocess.CompletedProcess:
    """Uruchom proces i podnieś czytelny błąd, gdy się nie powiedzie."""
    result = subprocess.run([str(item) for item in command],
                            cwd=str(cwd or ROOT), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        tail = (result.stdout or "")[-2000:] + (result.stderr or "")[-2000:]
        raise SystemExit(f"polecenie nie powiodło się ({result.returncode}):\n"
                         f"{' '.join(str(item) for item in command)}\n\n{tail}")
    return result
