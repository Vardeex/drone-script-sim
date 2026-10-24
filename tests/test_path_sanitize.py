"""Testy jednostkowe sanityzacji ścieżek (:mod:`app.path_sanitize`).

Regresja KNOWN_ISSUES KI-6: poprzednia wersja opierała się na jednym wyrażeniu
regularnym pisanym pod Windows i na Linuksie/macOS sklejała ścieżki **wewnątrz**
projektu (``app/adapters/.../__init__.py`` → ``app__init__.py``).

Zasady (sprawdzane dla obu stylów zapisu):
* ścieżka **wewnątrz projektu** → **względna** z separatorami ``/``,
* ścieżka **spoza projektu** → **sama nazwa pliku**.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.path_sanitize import sanitize_path, sanitize_text

WIN_PROJECT = Path("C:/projekty/DroneSim")
POSIX_PROJECT = Path("/home/x/proj")


# ------------------------------------------------------------------ wewnątrz projektu
@pytest.mark.parametrize("raw,expected", [
    # Windows - separator \ i /
    (r"C:\projekty\DroneSim\app\adapters\tello\djitellopy\__init__.py",
     "app/adapters/tello/djitellopy/__init__.py"),
    ("C:/projekty/DroneSim/app/runner.py", "app/runner.py"),
    (r"C:\projekty\DroneSim\lib\dronemoves\dronemoves\pilot.py",
     "lib/dronemoves/dronemoves/pilot.py"),
    ("C:/projekty/DroneSim", "."),
])
def test_windows_path_inside_project_becomes_relative(raw, expected):
    assert sanitize_path(raw, WIN_PROJECT) == expected


@pytest.mark.parametrize("raw,expected", [
    # POSIX - dokładnie ten przypadek, który padał w CI
    ("/home/x/proj/app/adapters/tello/djitellopy/__init__.py",
     "app/adapters/tello/djitellopy/__init__.py"),
    ("/home/x/proj/app/runner.py", "app/runner.py"),
    ("/home/x/proj/tests/test_server_api.py", "tests/test_server_api.py"),
    ("/home/x/proj", "."),
])
def test_posix_path_inside_project_becomes_relative(raw, expected):
    assert sanitize_path(raw, POSIX_PROJECT) == expected


def test_inside_project_path_never_collapses_to_directory_name():
    """Regresja: ``app/.../__init__.py`` nie może stać się ``app__init__.py``."""
    raw = "/home/runner/work/repo/repo/app/adapters/tello/djitellopy/__init__.py"
    result = sanitize_path(raw, Path("/home/runner/work/repo/repo"))
    assert result == "app/adapters/tello/djitellopy/__init__.py"
    assert "app__init__" not in result


# -------------------------------------------------------------------- spoza projektu
@pytest.mark.parametrize("raw,expected", [
    (r"C:\Users\x\AppData\Local\Temp\dronesim_ab12\script.py", "script.py"),
    ("C:/Users/x/AppData/Local/Temp/dronesim_ab12/skrypt.py", "skrypt.py"),
    (r"C:\Program Files\Python311\Lib\json\__init__.py", "__init__.py"),
    (r"\\serwer\udzial\katalog\modul.py", "modul.py"),
])
def test_windows_path_outside_project_becomes_file_name(raw, expected):
    assert sanitize_path(raw, WIN_PROJECT) == expected


@pytest.mark.parametrize("raw,expected", [
    ("/tmp/dronesim_ab12/script.py", "script.py"),
    ("/tmp/pytest-123/test_plik.py", "test_plik.py"),
    ("/home/x/Dokumenty/projekty/moj_skrypt.py", "moj_skrypt.py"),
    ("/Users/x/Library/Caches/pip/http/cache.py", "cache.py"),
    ("/usr/lib/python3.11/traceback.py", "traceback.py"),
])
def test_posix_path_outside_project_becomes_file_name(raw, expected):
    assert sanitize_path(raw, POSIX_PROJECT) == expected


def test_user_name_never_leaks():
    """Nazwa użytkownika z katalogu domowego nie może trafić do tekstu."""
    for raw, project in [
        (r"C:\Users\jan.kowalski\AppData\Local\Temp\dronesim_1\script.py", WIN_PROJECT),
        ("/home/jan.kowalski/projekty/skrypt.py", POSIX_PROJECT),
        ("/Users/jan.kowalski/Desktop/skrypt.py", POSIX_PROJECT),
    ]:
        result = sanitize_path(raw, project)
        assert "jan.kowalski" not in result
        assert result == "script.py" or result == "skrypt.py"


# ---------------------------------------------------------------- cały tekst
def test_text_with_traceback_keeps_surrounding_characters():
    project = Path("/home/runner/work/repo/repo")
    text = (
        'Traceback (most recent call last):\n'
        '  File "/home/runner/work/repo/repo/app/adapters/tello/djitellopy/__init__.py", '
        "line 12, in <module>\n"
        '  File "/tmp/dronesim_ab12/script.py", line 2, in <module>\n'
    )
    result = sanitize_text(text, project)
    assert 'File "app/adapters/tello/djitellopy/__init__.py", line 12' in result
    assert 'File "script.py", line 2' in result
    assert "/home/runner" not in result
    assert "/tmp/dronesim_ab12" not in result


def test_text_with_windows_paths():
    text = r'File "C:\projekty\DroneSim\app\runner.py", line 3' + "\n" + \
           r"tmp: C:\Users\x\AppData\Local\Temp\dronesim_9\script.py"
    result = sanitize_text(text, WIN_PROJECT)
    assert 'File "app/runner.py", line 3' in result
    assert "tmp: script.py" in result
    assert "Users" not in result


def test_text_without_paths_is_unchanged():
    text = "print('witaj')\n0 bledow, 0 ostrzezen\nwynik = 42"
    assert sanitize_text(text, WIN_PROJECT) == text


def test_relative_and_trailing_punctuation():
    """Ścieżka względna nie jest ruszana; kropka/przecinek po ścieżce zostają."""
    assert sanitize_text("app/adapters/tello/__init__.py", WIN_PROJECT) \
        == "app/adapters/tello/__init__.py"
    result = sanitize_text("patrz (/home/x/proj/app/runner.py).", POSIX_PROJECT)
    assert result == "patrz (app/runner.py)."


def test_quotes_around_path_are_preserved_by_text_sanitizer():
    project = Path("/home/x/proj")
    result = sanitize_text('File "/tmp/abc/skrypt.py"', project)
    assert result == 'File "skrypt.py"'
