"""Testy kodowania konsoli: polskie znaki nie mogą wywalić skryptu na cp1252.

Konsola runnera GitHub Actions (windows-latest) używa cp1252, więc
``print("włączone…")`` kończyło się ``UnicodeEncodeError``. Zabezpieczenie ma dwie
warstwy i obie są tu sprawdzane:

1. ``env`` w workflowach (``PYTHONUTF8``/``PYTHONIOENCODING``) - sprawdzamy YAML,
2. ``sys.stdout.reconfigure(encoding="utf-8", errors="replace")`` na starcie
   każdego skryptu konsolowego - sprawdzamy **działanie** w podprocesie
   z wymuszonym ``PYTHONIOENCODING=cp1252`` i bez ``PYTHONUTF8``.

Do tego notatki wydania: plik musi być UTF-8 **bez BOM** (trafia do
``gh release create --notes-file``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: skrypty uruchamiane z konsoli, które wypisują polskie znaki
CONSOLE_SCRIPTS = (
    "release_tools/build_portable.py",
    "release_tools/smoke_portable.py",
    "release_tools/changelog_notes.py",
    "release_tools/codemirror/collect_licenses.py",
    "docs/poradnik/make_screens.py",
    "examples/basic_square.py",
    "examples/climb_and_rotate.py",
    "examples/mission_pads_demo.py",
    "examples/rc_control.py",
    "lib/dronemoves/examples/calibrate.py",
    "lib/dronemoves/examples/maneuvers_showcase.py",
    "lib/dronemoves/examples/preflight_demo.py",
)

WORKFLOWS = (".github/workflows/release.yml", ".github/workflows/tests.yml")
#: polskie znaki używane w testach (każdy inny niż w ASCII)
POLSKI = "włączone site-packages: ąćęłńóśźż"


def cp1252_env() -> dict:
    """Środowisko jak na runnerze: konsola cp1252, **bez** ``PYTHONUTF8``."""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def run_python(args, env: dict, timeout: int = 120) -> subprocess.CompletedProcess:
    """Uruchom Pythona i zwróć wynik z **bajtowym** stdout/stderr."""
    return subprocess.run([sys.executable, *args], cwd=str(PROJECT_ROOT), env=env,
                          capture_output=True, timeout=timeout)


# --------------------------------------------------- 1. env w workflowach
@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_workflow_sets_utf8_env(workflow: str):
    """Oba workflow ustawiają `PYTHONUTF8` i `PYTHONIOENCODING` dla wszystkich jobów."""
    data = yaml.safe_load((PROJECT_ROOT / workflow).read_text(encoding="utf-8"))
    env = data.get("env") or {}
    assert env.get("PYTHONUTF8") == "1", f"{workflow}: {env}"
    assert env.get("PYTHONIOENCODING") == "utf-8", f"{workflow}: {env}"
    # env na poziomie workflow dziedziczą wszystkie joby - sprawdzamy, że nie
    # został nadpisany pustym słownikiem w którymś jobie
    for name, job in (data.get("jobs") or {}).items():
        job_env = job.get("env") or {}
        assert job_env.get("PYTHONIOENCODING", "utf-8") == "utf-8", name


# ------------------------------------------- 2. ochrona w kodzie skryptów
@pytest.mark.parametrize("script", CONSOLE_SCRIPTS)
def test_script_reconfigures_console(script: str):
    """Każdy skrypt konsolowy przełącza stdout/stderr na UTF-8 z `errors="replace"`."""
    source = (PROJECT_ROOT / script).read_text(encoding="utf-8")
    assert 'reconfigure(encoding="utf-8", errors="replace")' in source, script
    assert "sys.stderr" in source and "sys.stdout" in source, script


# ------------------------------- 3. regresja: cp1252 musi przejść bez wyjątku
def test_print_survives_cp1252():
    """``_print`` z polskim tekstem nie może rzucić `UnicodeEncodeError` na cp1252."""
    code = ("from release_tools.build_portable import _print; "
            f"_print({POLSKI!r})")
    result = run_python(["-c", code], cp1252_env())
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert "UnicodeEncodeError" not in stderr, stderr
    # wyjście jest już UTF-8 (bo skrypt przełączył strumień na starcie)
    assert POLSKI in result.stdout.decode("utf-8")


def test_build_portable_help_survives_cp1252():
    """``--help`` (argparse + import modułu) działa na konsoli cp1252."""
    result = run_python(["release_tools/build_portable.py", "--help"], cp1252_env())
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert "UnicodeEncodeError" not in stderr, stderr
    assert "usage" in result.stdout.decode("utf-8").lower()


def test_utf8_console_tolerates_missing_reconfigure(monkeypatch):
    """Brak `reconfigure` (starszy Python, podmieniony strumień) nie może psuć skryptu."""
    from release_tools import build_portable

    class BezReconfigure:
        def write(self, _text):
            return 0

        def flush(self):
            return None

    monkeypatch.setattr(sys, "stdout", BezReconfigure())
    monkeypatch.setattr(sys, "stderr", BezReconfigure())
    build_portable._utf8_console()          # nie podnosi wyjątku


# --------------------------------- 4. notatki wydania: UTF-8 bez BOM i polskie znaki
def test_changelog_notes_write_utf8_without_bom(tmp_path: Path):
    """Notatki dla `--notes-file` są UTF-8 bez BOM i zachowują polskie znaki."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [0.3.0] - 2026-10-25\n\n"
        "* Wdrożono polskie znaki: ąćęłńóśźż „cudzysłowy” — i myślniki\n",
        encoding="utf-8")
    out = tmp_path / "release_notes.md"
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import sys\n"
        "from release_tools.changelog_notes import main\n"
        "sys.exit(main(sys.argv[1:]))\n", encoding="utf-8")

    result = run_python([str(driver), "--version", "v0.3.0",
                         "--changelog", str(changelog), "--out", str(out)],
                        cp1252_env())
    stderr = result.stderr.decode("utf-8", "replace")
    assert result.returncode == 0, stderr
    assert "UnicodeEncodeError" not in stderr, stderr

    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "notatki nie mogą mieć BOM"
    text = raw.decode("utf-8")                 # brak wyjątku = poprawny UTF-8
    assert "ąćęłńóśźż" in text
    assert "0.3.0" in text or "Wdrożono" in text
