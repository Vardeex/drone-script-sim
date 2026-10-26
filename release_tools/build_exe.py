"""Buduje launcher ``DroneSim.exe`` (PyInstaller) do paczki i instalatora.

Wybór trybu: **onedir** (katalog ``_launcher`` obok ``DroneSim.exe``), a nie
onefile. Uzasadnienie (mniejsze ryzyko fałszywych alarmów antywirusów):

* onefile rozpakowuje się przy każdym starcie do ``%TEMP%`` i uruchamia się
  z kopii - to klasyczny wzorzec, który heurystyki AV oznaczają jako
  podejrzany („self-extracting executable w temp”),
* onedir uruchamia plik z miejsca instalacji, bez samorozpakowywania; dostaje
  też zwykle mniej flag reputacyjnych przy niepodpisanych plikach,
* ``--contents-directory _launcher`` sprawia, że obok ``start.bat`` leży
  **tylko** ``DroneSim.exe``, a biblioteki siedzą w podkatalogu ``_launcher``
  (nie mylą się z plikami aplikacji i nie trzeba ich przenosić).

Dodatkowo: ``--noupx`` (kompresja UPX bywa oznaczana jako podejrzana),
brak konsoli (``--windowed``), ikona z ``make_icon.py`` i metadane wersji
(nazwa produktu, wersja z ``app/__init__.py``, autor Vardeex).

Uruchomienie::

    python release_tools/build_exe.py              # zbuduj do dist/launcher
    python release_tools/build_exe.py --check      # tylko sprawdź, czy jest
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

try:                                   # uruchomienie jako moduł (testy)
    from release_tools.common import app_version, run, utf8_console, version_tuple
except ImportError:                    # uruchomienie jako skrypt
    from common import app_version, run, utf8_console, version_tuple

utf8_console()

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = Path(__file__).resolve().parent / "launcher" / "dronesim_launcher.py"
ICON = Path(__file__).resolve().parent / "assets" / "dronesim.ico"
DEFAULT_OUT = ROOT / "dist" / "launcher"
#: katalog z PyInstallerem (poza repo - ``tools/`` jest w ``.gitignore``)
BUILD_VENV = ROOT / "tools" / "pyi-venv"
BUILD_VENV_PYTHON = BUILD_VENV / "Scripts" / "python.exe"
#: przypięta wersja PyInstallera (ta sama lokalnie i w CI)
PYINSTALLER_VERSION = "6.22.3"
#: nazwa katalogu z bibliotekami obok ``DroneSim.exe``
CONTENTS_DIR = "_launcher"

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Vardeex'),
        StringStruct('FileDescription', 'Drone Script Simulator - launcher'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'DroneSim'),
        StringStruct('LegalCopyright', 'MIT License'),
        StringStruct('OriginalFilename', 'DroneSim.exe'),
        StringStruct('ProductName', 'Drone Script Simulator'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def ensure_pyinstaller() -> Path:
    """Zwróć ścieżkę do ``python.exe`` ze PyInstallerem (utwórz venv w ``tools/``)."""
    if BUILD_VENV_PYTHON.exists():
        probe = subprocess.run([str(BUILD_VENV_PYTHON), "-c", "import PyInstaller"],
                               capture_output=True)
        if probe.returncode == 0:
            return BUILD_VENV_PYTHON
    print(f"[exe] tworzę środowisko budowania: {BUILD_VENV}")
    BUILD_VENV.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "venv", str(BUILD_VENV)])
    run([str(BUILD_VENV_PYTHON), "-m", "pip", "install", "--no-cache-dir",
         f"pyinstaller=={PYINSTALLER_VERSION}"])
    return BUILD_VENV_PYTHON


def write_version_file(path: Path, version: str) -> Path:
    """Plik metadanych wersji dla ``DroneSim.exe`` (PyInstaller ``--version-file``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(VERSION_TEMPLATE.format(version=version,
                                            version_tuple=version_tuple(version)),
                    encoding="utf-8")
    return path


def build(out_dir: Path = DEFAULT_OUT) -> Path:
    """Zbuduj ``DroneSim.exe`` + katalog ``_launcher`` i zwróć ścieżkę exe."""
    version = app_version()
    python = ensure_pyinstaller()
    work = ROOT / "tmp" / "pyi-build"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    version_file = write_version_file(work / "version_info.txt", version)
    print(f"[exe] buduję launcher {version} (PyInstaller onedir, bez UPX)")

    command: List[str] = [
        str(python), "-m", "PyInstaller",
        "--noconfirm", "--clean", "--log-level", "WARN",
        "--onedir",                       # mniej alarmów AV niż onefile
        "--contents-directory", CONTENTS_DIR,
        "--windowed",                     # bez okna konsoli
        "--noupx",
        "--name", "DroneSim",
        "--icon", str(ICON),
        "--version-file", str(version_file),
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "build"),
        "--specpath", str(work),
        "--paths", str(Path(__file__).resolve().parent / "launcher"),
        str(LAUNCHER),
    ]
    run(command)

    built = work / "dist" / "DroneSim"
    exe = built / "DroneSim.exe"
    if not exe.exists():
        raise SystemExit(f"PyInstaller nie utworzył {exe}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in ("DroneSim.exe", CONTENTS_DIR):
        target = out_dir / stale
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
    shutil.copy2(exe, out_dir / "DroneSim.exe")
    shutil.copytree(built / CONTENTS_DIR, out_dir / CONTENTS_DIR)
    shutil.copy2(ICON, out_dir / ICON.name)     # ikona dla zasobnika
    size = sum(path.stat().st_size for path in out_dir.rglob("*") if path.is_file())
    print(f"[exe] gotowe: {out_dir / 'DroneSim.exe'} "
          f"({(out_dir / 'DroneSim.exe').stat().st_size // 1024} kB, "
          f"całość {size / 1024 / 1024:.1f} MB)")
    return out_dir / "DroneSim.exe"


def check(out_dir: Path = DEFAULT_OUT) -> int:
    """Sprawdź, czy launcher jest zbudowany (dla CI i testów)."""
    exe = out_dir / "DroneSim.exe"
    contents = out_dir / CONTENTS_DIR
    ok = exe.exists() and contents.is_dir()
    size = exe.stat().st_size // 1024 if exe.exists() else 0
    print(f"[exe] {exe}: {'OK' if ok else 'BRAK'} ({size} kB, "
          f"katalog {CONTENTS_DIR}: {'jest' if contents.is_dir() else 'brak'})")
    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Buduje launcher DroneSim.exe")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--check", action="store_true",
                        help="tylko sprawdź, czy launcher istnieje")
    args = parser.parse_args(list(argv) if argv is not None else None)
    out_dir = Path(args.out)
    if args.check:
        return check(out_dir)
    build(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
