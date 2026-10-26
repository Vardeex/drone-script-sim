"""Testy narzędzi wydania: launcher, ikona, instalator, workflow.

Nie budujemy tu EXE ani instalatora (to robi ``release_tools/smoke_installer.py``
i CI) - sprawdzamy **kontrakt**: pliki, dyrektywy Inno Setup, metadane wersji
i to, że workflow publikuje dokładnie trzy pliki wydania.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_DIR = ROOT / "release_tools" / "launcher"
ICON = ROOT / "release_tools" / "assets" / "dronesim.ico"
ISS = ROOT / "release_tools" / "installer" / "dronesim.iss"
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"


def load_launcher():
    """Wczytaj moduł launchera z pliku (nie jest paczką importowalną)."""
    path = LAUNCHER_DIR / "dronesim_launcher.py"
    spec = importlib.util.spec_from_file_location("dronesim_launcher_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher():
    if not sys.platform.startswith("win"):
        pytest.skip("launcher jest tylko dla Windows (Win32 API)")
    return load_launcher()


# ------------------------------------------------------------------ ikona
def test_icon_is_valid_ico_with_many_sizes():
    """Ikona to prawdziwy ICO z rozmiarami 16-256 px (nie placeholder)."""
    data = ICON.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"          # nagłówek ICO
    count = int.from_bytes(data[4:6], "little")
    assert count >= 5, count
    dimensions = sorted(data[6 + 16 * index] or 256 for index in range(count))
    assert dimensions[0] <= 16 and dimensions[-1] == 256, dimensions
    assert b"\x89PNG" in data                       # wpisy PNG


def test_icon_has_no_vendor_branding():
    """Ikona jest własna - nie kopiujemy logo DJI/Tello (brak plików marki)."""
    suspicious = [path.name for path in (ROOT / "release_tools").rglob("*")
                  if path.is_file() and any(token in path.name.lower()
                                            for token in ("dji", "tello"))]
    assert suspicious == [], suspicious


# ---------------------------------------------------------------- launcher
def test_data_dir_precedence(launcher, tmp_path, monkeypatch):
    """``--data-dir`` > ``DRONESIM_DATA_DIR`` > ``launcher.json`` > katalog paczki."""
    root = tmp_path / "pakiet"
    root.mkdir()
    cli = tmp_path / "z-cli"
    env = tmp_path / "z-env"
    config = tmp_path / "z-config"
    (root / "launcher.json").write_text(
        json.dumps({"data_dir": str(config)}), encoding="utf-8")

    assert launcher.resolve_data_dir(str(cli), root) == cli.resolve()
    monkeypatch.setenv("DRONESIM_DATA_DIR", str(env))
    assert launcher.resolve_data_dir(None, root) == env.resolve()
    monkeypatch.delenv("DRONESIM_DATA_DIR")
    assert launcher.resolve_data_dir(None, root) == config.resolve()
    (root / "launcher.json").unlink()
    assert launcher.resolve_data_dir(None, root) == root.resolve()


def test_python_executable_never_returns_frozen_launcher(launcher, tmp_path):
    """W paczce serwer startuje z ``python\\python.exe`` (nie z samego launchera)."""
    package = tmp_path / "paczka"
    package.mkdir()
    # bez python/ i bez zamrożenia -> tryb dev: bieżący interpreter
    assert launcher.python_executable(package) == Path(sys.executable)
    bundled = package / "python" / "python.exe"
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    assert launcher.python_executable(package) == bundled


def test_parse_args_for_tests(launcher):
    """``--no-browser``, ``--no-tray``, ``--port`` i brak ``--stop-file``."""
    args = launcher.parse_args(["--no-browser", "--no-tray", "--port", "9999"])
    assert args.no_browser and args.no_tray and args.port == 9999
    assert args.stop_file is None


# --------------------------------------------------------------- instalator
def test_installer_is_per_user_without_admin():
    """Instalacja per-użytkownik do %LOCALAPPDATA%\\Programs, bez administratora."""
    text = ISS.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert r"DefaultDirName={localappdata}\Programs\{#AppShortName}" in text
    assert "UninstallDisplayName=" in text
    assert 'Name: "desktopicon"' in text           # opcjonalny skrót na pulpicie
    assert "postinstall" in text                   # uruchomienie po instalacji
    assert 'Source: "{#SourceDir}\\*"' in text


def test_installer_keeps_user_data_outside_program_dir():
    """Dane w %LOCALAPPDATA%\\DroneSim - deinstalator pyta, tryb cichy nie kasuje."""
    text = ISS.read_text(encoding="utf-8")
    assert r"DefaultDataDir = '{localappdata}\DroneSim'" in text
    assert "launcher.json" in text
    assert "UninstallSilent()" in text             # cicha deinstalacja nie pyta
    assert "{param:DELETEUSERDATA|0}" in text      # jawne usunięcie danych
    assert "DelTree(Folder" in text
    assert "JsonPath" in text                      # ścieżka JSON z escapowaniem
    assert "procedure CurUninstallStepChanged" in text


def test_installer_has_stable_app_id():
    """Ten sam AppId w kolejnych wersjach = aktualizacja bez deinstalacji."""
    text = ISS.read_text(encoding="utf-8")
    app_id = [line for line in text.splitlines() if line.startswith("AppId=")]
    assert len(app_id) == 1, app_id
    assert "{{6F1C3B52" in app_id[0]               # stały GUID (nie losowy)


# ----------------------------------------------------------------- workflow
def test_release_workflow_publishes_three_files():
    """Wydanie publikuje instalator, paczkę i SHA256SUMS.txt (po testach dymnych)."""
    text = RELEASE_YML.read_text(encoding="utf-8")
    assert "build_exe.py" in text
    assert "build_portable.py" in text
    assert "build_installer.py" in text
    assert "smoke_portable.py" in text
    assert "smoke_installer.py" in text
    assert "SHA256SUMS.txt" in text
    assert "innosetup-6.7.3.exe" in text           # Inno Setup: wersja przypięta
    assert "gh release create $tag $setup $zip $sums" in text
    # kolejność: launcher przed paczką (paczka zawiera DroneSim.exe)
    assert text.index("build_exe.py") < text.index("build_portable.py")
    # testy dymne przed publikacją
    assert text.index("smoke_installer.py") < text.index("gh release create")


def test_build_exe_metadata_and_mode():
    """Launcher: onedir (nie onefile), bez UPX, z metadanymi wersji i ikoną."""
    text = (ROOT / "release_tools" / "build_exe.py").read_text(encoding="utf-8")
    assert "--onedir" in text
    assert "--onefile" not in text
    assert "--noupx" in text
    assert "--icon" in text and "--version-file" in text
    assert "CompanyName', 'Vardeex'" in text
    assert "ProductName', 'Drone Script Simulator'" in text
    assert '"6.22.3"' in text                      # przypięty PyInstaller


def test_smoke_installer_uses_isolated_dirs():
    """Test dymny instaluje do tmp i używa własnego katalogu danych."""
    text = (ROOT / "release_tools" / "smoke_installer.py").read_text(encoding="utf-8")
    assert "/VERYSILENT" in text and "/CURRENTUSER" in text
    assert "/DATA=" in text and "/DIR=" in text
    assert "smoke-installer" in text
    assert "/DELETEUSERDATA=1" in text
    assert "/api/health" in text


def test_release_tools_pass_pyflakes():
    """Nowe skrypty wydania są czyste w pyflakes (jak reszta repozytorium)."""
    result = subprocess.run([sys.executable, "-m", "pyflakes", str(ROOT / "release_tools")],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
