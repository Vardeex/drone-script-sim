"""Buduje instalator ``DroneSim-Setup-<wersja>.exe`` (Inno Setup 6).

Instalator pakuje **rozpakowaną** paczkę przenośną (ZIP z ``build_portable.py``),
więc nie budujemy jej drugi raz: skrypt rozpakowuje ZIP do ``tmp/installer-source``
i przekazuje katalog do Inno Setup jako ``/DSourceDir=...``.

Wymagania: Inno Setup 6 (``ISCC.exe``). Kolejność szukania:

1. ``--iscc ŚCIEŻKA``,
2. zmienna środowiskowa ``ISCC``,
3. ``tools/innosetup/ISCC.exe`` (instalacja lokalna do projektu),
4. ``ISCC.exe`` w ``PATH``,
5. ``%ProgramFiles(x86)%\\Inno Setup 6\\ISCC.exe``.

W CI (``windows-latest``) Inno Setup nie jest zainstalowany domyślnie - workflow
instaluje go z Chocolatey z **przypiętą wersją** (patrz ``release.yml``).

Uruchomienie::

    python release_tools/build_installer.py
    python release_tools/build_installer.py --zip dist/DroneSim-portable-0.4.0-win64.zip
    python release_tools/build_installer.py --check     # czy ISCC jest dostępny
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence

try:                                   # uruchomienie jako moduł (testy)
    from release_tools.common import app_version, run, utf8_console
except ImportError:                    # uruchomienie jako skrypt
    from common import app_version, run, utf8_console

utf8_console()

ROOT = Path(__file__).resolve().parent.parent
ISS = Path(__file__).resolve().parent / "installer" / "dronesim.iss"
LOCAL_ISCC = ROOT / "tools" / "innosetup" / "ISCC.exe"
DEFAULT_OUT = ROOT / "dist"
STAGE = ROOT / "tmp" / "installer-source"


def find_iscc(explicit: Optional[str] = None) -> Optional[Path]:
    """Znajdź ``ISCC.exe`` (Inno Setup) według kolejności z dokumentacji skryptu."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_value = os.environ.get("ISCC")
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(LOCAL_ISCC)
    which = shutil.which("ISCC")
    if which:
        candidates.append(Path(which))
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidates.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def unpack(zip_path: Path) -> Path:
    """Rozpakuj paczkę przenośną do ``tmp/installer-source`` i zwróć katalog."""
    if not zip_path.exists():
        raise SystemExit(
            f"brak paczki {zip_path} - najpierw uruchom build_portable.py")
    if STAGE.exists():
        shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(STAGE)
    roots = [item for item in STAGE.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise SystemExit(f"ZIP powinien mieć jeden katalog główny: {roots}")
    package = roots[0]
    if not (package / "DroneSim.exe").exists():
        raise SystemExit(f"w paczce brak DroneSim.exe: {package}")
    return package


def build(zip_path: Path, out_dir: Path, iscc: Optional[str]) -> Path:
    """Zbuduj instalator i zwróć ścieżkę pliku."""
    version = app_version()
    compiler = find_iscc(iscc)
    if compiler is None:
        raise SystemExit(
            "nie znaleziono ISCC.exe (Inno Setup 6).\n"
            "Lokalnie: zainstaluj Inno Setup do tools\\innosetup\n"
            "  (innosetup-6.7.3.exe /VERYSILENT /PORTABLE=1 "
            "/DIR=D:\\DroneSim\\tools\\innosetup)\n"
            "albo wskaż ścieżkę przez --iscc / zmienną ISCC.")
    package = unpack(zip_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[instalator] Inno Setup: {compiler}")
    print(f"[instalator] źródło: {package}")
    run([str(compiler), f"/DSourceDir={package}", f"/DAppVersion={version}",
         f"/O{out_dir}", str(ISS)])
    target = out_dir / f"DroneSim-Setup-{version}.exe"
    if not target.exists():
        raise SystemExit(f"Inno Setup nie utworzył {target}")
    print(f"[instalator] gotowe: {target} "
          f"({target.stat().st_size / 1024 / 1024:.1f} MB)")
    return target


def check(iscc: Optional[str] = None) -> int:
    """Sprawdź, czy ISCC jest dostępny (dla CI)."""
    compiler = find_iscc(iscc)
    print(f"[instalator] ISCC: {compiler if compiler else 'BRAK'}")
    return 0 if compiler else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Buduje instalator DroneSim")
    parser.add_argument("--zip", default=None, help="paczka przenośna (ZIP)")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--iscc", default=None, help="ścieżka do ISCC.exe")
    parser.add_argument("--check", action="store_true",
                        help="tylko sprawdź, czy ISCC jest dostępny")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.check:
        return check(args.iscc)
    version = app_version()
    zip_path = (Path(args.zip) if args.zip
                else ROOT / "dist" / f"DroneSim-portable-{version}-win64.zip")
    build(zip_path, Path(args.out), args.iscc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
