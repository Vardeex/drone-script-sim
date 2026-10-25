"""Testy budowy paczki przenośnej (bez pobierania Pythona i bez sieci).

Sprawdzamy logikę, która decyduje o zawartości paczki i o jej weryfikacji:

* filtr plików (``git ls-files`` + katalogi zabronione),
* lista zależności runtime (bez pytest/httpx i bez ``-e ./lib/dronemoves``),
* ``verify_zip`` - wykrywa ``.pyc``, ``.git``, ``flights``, ``scenes/user``
  i prawdziwą nazwę użytkownika, a **nie** zgłasza placeholderów ``C:\\Users\\x``
  ani kodu firm trzecich z ``site-packages``,
* ``enable_site_packages`` włącza ``import site`` (inaczej paczka nie zaimportuje
  zależności),
* ``start.bat`` używa wbudowanego Pythona i nie odwołuje się do ``.venv``.

Test pełnej budowy (pobranie Pythona, instalacja kół) jest osobno, poza pytest:
``release_tools/build_portable.py`` + ``release_tools/smoke_portable.py``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import release_tools.build_portable as builder
import release_tools.changelog_notes as notes


def test_app_version_matches_package():
    """Wersja z ``app/__init__.py`` jest czytana poprawnie (źródło nazwy paczki)."""
    from app import __version__

    assert builder.app_version() == __version__
    assert builder.dronemoves_version().count(".") >= 1


def test_tracked_files_excludes_forbidden_dirs():
    """Lista plików nie zawiera katalogów technicznych ani śmieci."""
    files = builder.tracked_files()
    assert "app/server.py" in files
    assert "examples/basic_square.py" in files
    assert "README.md" in files
    for name in files:
        for folder in ("__pycache__/", ".git/", ".github/", ".venv/", "tmp/",
                       "flights/", "scenes/user/", "lib/dronemoves/tests/"):
            assert f"/{folder}" not in f"/{name}", f"{folder} w {name}"
        assert not name.endswith((".pyc", ".pyo")), name
    # testy aplikacji nie trafiają do paczki dla użytkownika
    assert not any(name.startswith("tests/") for name in files)


def test_runtime_requirements_skip_dev_only(tmp_path: Path):
    """Zależności runtime: bez testów i bez instalacji edytowalnej biblioteki."""
    target = builder.runtime_requirements(tmp_path / "req.txt")
    text = target.read_text(encoding="utf-8")
    names = {line.lower().split("==")[0].split("[")[0].strip()
             for line in text.splitlines() if line}
    assert "-e " not in text
    assert "pytest" not in names and "httpx" not in names
    assert "fastapi" in names and "uvicorn" in names


def _make_zip(path: Path, entries: dict) -> Path:
    """Pomocniczy ZIP: ``{nazwa: treść}`` (treść ``None`` = pusty plik)."""
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, "" if content is None else content)
    return path


def test_verify_zip_accepts_clean_package(tmp_path: Path, monkeypatch):
    """Czysta paczka nie daje żadnych zastrzeżeń."""
    monkeypatch.setattr(builder.Path, "home", staticmethod(lambda: Path("/home/testuser")))
    archive = _make_zip(tmp_path / "ok.zip", {
        "pkg/start.bat": "@echo off\r\n",
        "pkg/app/server.py": "print('ok')\n",
        "pkg/docs/PORADNIK.md": "przyklad: C:\\Users\\x\\AppData (placeholder)\n",
        "pkg/python/Lib/site-packages/click/utils.py": "# C:\\Users\\Alice\\example\n",
    })
    assert builder.verify_zip(archive) == []


@pytest.mark.parametrize("entry", [
    "pkg/app/__pycache__/server.cpython-311.pyc",
    "pkg/.git/config",
    "pkg/.venv/Scripts/python.exe",
    "pkg/flights/lot.json",
    "pkg/scenes/user/moja.json",
    "pkg/tmp/roboczy.txt",
])
def test_verify_zip_rejects_forbidden_entries(tmp_path: Path, entry):
    """Każda zabroniona ścieżka jest wykrywana."""
    archive = _make_zip(tmp_path / "bad.zip", {entry: "x"})
    problems = builder.verify_zip(archive)
    assert problems, f"nie wykryto {entry}"


def test_verify_zip_detects_real_username_in_content(tmp_path: Path):
    """Prawdziwa nazwa użytkownika (builder) w treści pliku = wyciek."""
    user = Path.home().name
    archive = _make_zip(tmp_path / "leak.zip", {
        "pkg/app/config.py": f'PATH = r"C:\\Users\\{user}\\AppData\\Local"\n',
    })
    problems = builder.verify_zip(archive)
    assert any("nazwa użytkownika" in problem for problem in problems), problems


def test_enable_site_packages(tmp_path: Path):
    """``python311._pth`` po zmianie zawiera ``import site`` i site-packages."""
    path_file = tmp_path / "python311._pth"
    path_file.write_text("python311.zip\n.\n#import site\n", encoding="utf-8")
    builder.enable_site_packages(tmp_path)
    text = path_file.read_text(encoding="utf-8")
    assert "import site" in text
    assert "Lib\\site-packages" in text
    assert "#import site" not in text


def test_start_bat_uses_bundled_python(tmp_path: Path):
    """``start.bat`` wskazuje ``python\\python.exe`` i nie używa ``.venv``."""
    builder.write_start_bat(tmp_path)
    text = (tmp_path / "start.bat").read_text(encoding="utf-8")
    assert "python\\python.exe" in text
    assert ".venv" not in text
    assert "uvicorn app.server:app" in text
    assert text.startswith("@echo off")


# ------------------------------------------------- notatki wydania z CHANGELOG
SAMPLE_CHANGELOG = """# Changelog

## [Niewydane] - 2026-10-24

### Dodane

* nowa funkcja A

## [1.0.0] - 2026-10-20

### Dodane

* pierwsze wydanie

## [0.9.0] - 2026-10-01

### Naprawione

* cos starego
"""


def test_notes_for_exact_version():
    """Dokładna wersja jest znajdowana (także gdy tag ma prefiks ``v``)."""
    body = notes.notes_for(SAMPLE_CHANGELOG, "v1.0.0")
    assert "pierwsze wydanie" in body
    assert "nowa funkcja A" not in body


def test_notes_for_falls_back_to_unreleased():
    """Brak sekcji wersji -> używamy „Niewydane” (typowe przed wydaniem)."""
    body = notes.notes_for(SAMPLE_CHANGELOG, "v2.0.0")
    assert "nowa funkcja A" in body


def test_notes_for_falls_back_to_first_section():
    """Bez „Niewydane” bierzemy pierwszą sekcję, żeby notatki nie były puste."""
    body = notes.notes_for("## [0.5.0] - 2026-01-01\n\n* jedyna rzecz\n", "9.9.9")
    assert "jedyna rzecz" in body
