"""Buduje paczkę „rozpakuj i uruchom" dla Windows: ``DroneSim-portable-<wersja>-win64.zip``.

Paczka zawiera **oficjalny Python embeddable** (python.org) z zainstalowanymi
zależnościami, aplikację, przykłady, sceny, poradnik i ``start.bat``, który
używa wbudowanego Pythona - użytkownik nic nie instaluje w systemie.

Skąd bierzemy Pythona
---------------------
``https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip``
(3.11.9 to **ostatnie** wydanie 3.11 z plikami binarnymi; 3.11.17 jest
tylko źródłowe). Plik jest pobierany raz do ``cache/`` i weryfikowany:

* **SHA-256** - z tabeli „SHA-256 checksum" na stronie wydania python.org,
  gdy jest tam podana; dla 3.11.9 python.org podaje tylko MD5, więc SHA-256
  jest **przypięty w tym pliku** (``EMBED_SHA256``) i dodatkowo krzyżowo
  sprawdzany z **MD5 opublikowanym przez python.org** (``EMBED_MD5``),
* **MD5** - z tabeli plików na stronie wydania (ta sama wartość co
  ``EMBED_MD5``); rozbieżność przerywa budowę.

Uruchomienie
------------
    python release_tools/build_portable.py                # wersja z app/__init__.py
    python release_tools/build_portable.py --version 0.3.0 --out dist

Dlaczego nie ``tools/``: katalog ``tools/`` jest w ``.gitignore`` (lokalne
środowisko Pythona), więc skrypt budujący musi leżeć gdzie indziej.
``release_tools`` nie koliduje też z żadnym pakietem zależności (``packaging``
byłby ryzykowny - to nazwa prawdziwej biblioteki z ``requirements.txt``).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
DEFAULT_OUT = ROOT / "dist"

#: wersja Pythona w paczce (3.11 = wersja testowana w CI)
PYTHON_VERSION = "3.11.9"
EMBED_FILE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{EMBED_FILE}"
RELEASE_PAGE = "https://www.python.org/downloads/release/python-3119/"

#: SHA-256 oficjalnego ``python-3.11.9-embed-amd64.zip`` (11 249 023 B).
#: python.org nie publikuje SHA-256 dla 3.11.9 w tabeli plików - wartość jest
#: przypięta tutaj, a poprawność potwierdza MD5 z python.org (niżej).
EMBED_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
#: MD5 z tabeli plików na stronie wydania python.org (kolumna „MD5 checksum”).
EMBED_MD5 = "6d9aa08531d48fcc261ba667e2df17c4"

#: pakiety z ``requirements.txt`` potrzebne tylko w repozytorium (testy/CI)
DEV_ONLY = {
    "pytest", "iniconfig", "pluggy", "packaging", "Pygments",
    "httpx", "httpcore", "certifi",
}

#: co wchodzi do paczki (ścieżki względem repozytorium)
INCLUDE_PREFIXES = ("app/", "examples/", "scenes/", "docs/", "lib/dronemoves/",
                    "plugins/")
INCLUDE_FILES = ("config.json", "LICENSE", "README.md", "CHANGELOG.md",
                 "KNOWN_ISSUES.md")
#: czego nigdy nie pakujemy (katalogi - dopasowanie po fragmencie ścieżki)
EXCLUDE_DIRS = ("__pycache__/", "docs/ref/", ".git/", ".github/", ".venv/",
                "tmp/", "flights/", "scenes/user/", "dist/", "build/",
                ".pytest_cache/", "lib/dronemoves/tests/")
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".swp", ".log")


def _print(message: str) -> None:
    print(f"[portable] {message}", flush=True)


def app_version() -> str:
    """Wersja aplikacji z ``app/__init__.py`` (bez importu aplikacji)."""
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("nie znaleziono __version__ w app/__init__.py")
    return match.group(1)


def dronemoves_version() -> str:
    """Wersja biblioteki ``dronemoves`` z ``pyproject.toml``."""
    text = (ROOT / "lib" / "dronemoves" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


# ------------------------------------------------------------------ weryfikacja
def _hash_of(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def published_sha256(version: str = PYTHON_VERSION) -> Optional[str]:
    """SHA-256 pliku embeddable z tabeli na stronie wydania python.org.

    Nowsze wydania (3.12+) mają kolumnę „SHA-256 checksum”; dla 3.11.9 jej nie
    ma (tylko MD5), więc funkcja zwraca ``None`` i używamy wartości przypiętej.
    """
    url = (f"https://www.python.org/downloads/release/"
           f"python-{version.replace('.', '')}/")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            html = response.read().decode("utf-8", "replace")
    except Exception as exc:                      # noqa: BLE001 - brak sieci to nie błąd
        _print(f"nie udało się odczytać strony python.org ({exc}) - pomijam")
        return None
    # wiersz tabeli z nazwą pliku; szukamy 64-znakowego hexa w tym wierszu
    for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        if EMBED_FILE.replace("-", "&#8209;") in row or EMBED_FILE in row:
            found = re.findall(r"\b([0-9a-f]{64})\b", row)
            if found:
                return found[-1]
    return None


def fetch_embedded_python() -> Path:
    """Pobierz (raz, do ``cache/``) i zweryfikuj oficjalny Python embeddable."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / EMBED_FILE
    if target.exists():
        if _hash_of(target) == EMBED_SHA256:
            _print(f"używam z cache: {target.name}")
            return target
        _print("plik w cache ma złą sumę - pobieram ponownie")
        target.unlink()

    _print(f"pobieram {EMBED_URL}")
    with urllib.request.urlopen(EMBED_URL, timeout=180) as response, \
            target.open("wb") as handle:
        shutil.copyfileobj(response, handle)

    sha = _hash_of(target)
    expected = published_sha256() or EMBED_SHA256
    if sha != expected:
        target.unlink()
        raise SystemExit(f"zła suma SHA-256 pliku Pythona: {sha} != {expected}")
    if sha != EMBED_SHA256:
        raise SystemExit(f"python.org podaje inną sumę niż przypięta: {sha}")
    md5 = _hash_of(target, "md5")
    if md5 != EMBED_MD5:
        target.unlink()
        raise SystemExit(f"zła suma MD5 (python.org: {EMBED_MD5}, plik: {md5})")
    _print(f"sumy OK (sha256 {sha[:12]}…, md5 {md5[:12]}…)")
    return target


# --------------------------------------------------------------------- zawartość
def _excluded(relative: str) -> bool:
    """Czy plik wypada z paczki (katalogi zabronione albo rozszerzenie techniczne)."""
    prefixed = f"/{relative}"
    if any(f"/{folder}" in prefixed for folder in EXCLUDE_DIRS):
        return True
    return relative.endswith(EXCLUDE_SUFFIXES)


def tracked_files() -> List[str]:
    """Pliki do paczki: z ``git ls-files`` (bez nieśledzonych śmieci).

    Gdy ``git`` nie jest dostępny (np. rozpakowane archiwum), przechodzimy
    drzewo katalogów i stosujemy te same filtry.
    """
    try:
        output = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT),
                                capture_output=True, check=True).stdout
        names = [name for name in output.decode("utf-8").split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        _print("git niedostępny - zbieram pliki z drzewa katalogów")
        names = [str(path.relative_to(ROOT)).replace("\\", "/")
                 for path in ROOT.rglob("*") if path.is_file()]

    selected = []
    for name in names:
        name = name.replace("\\", "/")
        if _excluded(name):
            continue
        if name in INCLUDE_FILES or name.startswith(INCLUDE_PREFIXES):
            selected.append(name)
    return sorted(set(selected))


def runtime_requirements(target: Path) -> Path:
    """Utwórz listę zależności runtime (bez testów i bez ``-e ./lib/dronemoves``)."""
    lines: List[str] = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-e "):
            continue
        name = re.split(r"[=<>!\[;]", stripped, maxsplit=1)[0].strip().lower()
        if name in DEV_ONLY:
            continue
        lines.append(stripped)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# ----------------------------------------------------------------- instalacja
def _pip(args: Sequence[str]) -> None:
    command = [sys.executable, "-m", "pip", *args]
    result = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"pip {' '.join(args)} nie powiódł się:\n"
                           f"{result.stdout[-3000:]}\n{result.stderr[-3000:]}")


def install_runtime(site_packages: Path, requirements: Path) -> None:
    """Zainstaluj zależności runtime do ``site-packages`` embeddowanego Pythona.

    ``--target`` + ``--python-version 3.11`` + ``--platform win_amd64`` dają
    właściwe koła (binarne) bez uruchamiania embeddowanego interpretera (ten
    nie ma pip). Gdy pip odmówi takiej kombinacji, awaryjnie pobieramy koła
    i rozpakowujemy je ręcznie.
    """
    site_packages.mkdir(parents=True, exist_ok=True)
    common = ["--only-binary", ":all:", "--no-compile", "--no-cache-dir",
              "--python-version", "3.11", "--platform", "win_amd64",
              "--implementation", "cp", "--abi", "cp311"]
    try:
        _pip(["install", *common, "--target", str(site_packages), "-r", str(requirements)])
        return
    except RuntimeError as exc:
        _print(f"pip --target nie zadziałał ({str(exc).splitlines()[0]}) - "
               "pobieram koła i rozpakowuję")

    with tempfile.TemporaryDirectory(prefix="dronesim_wheels_") as folder:
        wheels = Path(folder)
        _pip(["download", *common, "--dest", str(wheels), "-r", str(requirements)])
        for wheel in sorted(wheels.glob("*.whl")):
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(site_packages)


def copy_dronemoves(site_packages: Path) -> None:
    """Wklej czysty pakiet ``dronemoves`` (zamiast instalacji edytowalnej)."""
    source = ROOT / "lib" / "dronemoves" / "dronemoves"
    target = site_packages / "dronemoves"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # minimalne metadane, żeby `pip list`/`importlib.metadata` widziały bibliotekę
    version = dronemoves_version()
    info = site_packages / f"dronemoves-{version}.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\n"
        f"Name: dronemoves\nVersion: {version}\n"
        "Summary: Plynne manewry drona (Tello) - symulator i prawdziwy dron\n",
        encoding="utf-8")
    (info / "WHEEL").write_text(
        "Wheel-Version: 1.0\nGenerator: build_portable\nRoot-Is-Purelib: true\n"
        "Tag: py3-none-any\n", encoding="utf-8")
    (info / "top_level.txt").write_text("dronemoves\n", encoding="utf-8")


def enable_site_packages(python_dir: Path) -> None:
    """Włącz ``site`` w ``python3XX._pth`` (inaczej importy z site-packages nie działają)."""
    pth_files = sorted(python_dir.glob("python3*._pth"))
    if not pth_files:
        raise SystemExit("brak pliku python3XX._pth w paczce embeddable")
    path_file = pth_files[0]
    lines = ["python311.zip", ".", "Lib\\site-packages", "import site", ""]
    path_file.write_text("\n".join(lines), encoding="utf-8")
    _print(f"włączone site-packages w {path_file.name}")


def write_start_bat(package_dir: Path) -> None:
    """``start.bat`` używający wbudowanego Pythona (bez instalacji w systemie)."""
    content = r"""@echo off
REM ===========================================================================
REM  Drone Script Simulator - wersja przenosna (bez instalacji)
REM
REM  Uzywa Pythona dolaczonego w katalogu python\ - nic nie instaluje w systemie.
REM  Zamkniecie tego okna zatrzymuje serwer.
REM
REM  Port: domyslnie 8765; mozna zmienic zmienna PORT (tylko biezaca sesja).
REM ===========================================================================
setlocal

cd /d "%~dp0"
if "%PORT%"=="" set "PORT=8765"

if not exist "python\python.exe" goto :brak_pythona

REM Jeden serwer na raz: jesli port zajety, tylko otwieramy przegladarke.
"python\python.exe" "%~dp0app\port_busy.py" %PORT%
if not errorlevel 1 goto :juz_dziala

echo Uruchamiam Drone Script Simulator na http://127.0.0.1:%PORT% ...
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:%PORT%/"
"python\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port %PORT%
goto :koniec

:juz_dziala
echo Serwer juz dziala na http://127.0.0.1:%PORT% - otwieram przegladarke.
start "" "http://127.0.0.1:%PORT%/"
timeout /t 3 /nobreak >nul
goto :koniec

:brak_pythona
echo BLAD: brak pliku python\python.exe - paczka jest niekompletna.
echo Rozpakuj caly ZIP (nie kopiuj pojedynczych plikow).
pause

:koniec
endlocal
"""
    (package_dir / "start.bat").write_text(content.replace("\n", "\r\n"),
                                           encoding="utf-8", newline="")


def write_readme_first(package_dir: Path, version: str) -> None:
    """Krótka instrukcja na pierwszym miejscu (dla osoby, która rozpakuje ZIP)."""
    text = f"""Drone Script Simulator {version} - wersja przenosna (Windows 64-bit)
================================================================

1. Rozpakuj CALY plik ZIP do dowolnego katalogu (np. D:\\DroneSim).
2. Kliknij dwa razy `start.bat`.
3. Przegladarka otworzy sie na http://127.0.0.1:8765/

Nic nie jest instalowane w systemie - Python jest w katalogu `python\\`.
Aby usunac program, skasuj katalog z rozpakowana paczka.

Dokumentacja: `docs\\PORADNIK.md` (krok po kroku) i `README.md`.
"""
    (package_dir / "PRZECZYTAJ.txt").write_text(text.replace("\n", "\r\n"),
                                                encoding="utf-8", newline="")


# ------------------------------------------------------------------- pakowanie
def assemble(package_dir: Path, embedded: Path) -> None:
    """Złóż zawartość paczki w ``package_dir`` (jeszcze bez ZIP-a)."""
    package_dir.mkdir(parents=True, exist_ok=True)

    python_dir = package_dir / "python"
    python_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(embedded) as archive:
        archive.extractall(python_dir)
    enable_site_packages(python_dir)

    site_packages = python_dir / "Lib" / "site-packages"
    with tempfile.TemporaryDirectory(dir=str(ROOT / "tmp")) as folder:
        requirements = runtime_requirements(Path(folder) / "requirements-runtime.txt")
        install_runtime(site_packages, requirements)
    copy_dronemoves(site_packages)

    for name in tracked_files():
        source = ROOT / name
        destination = package_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    write_start_bat(package_dir)
    write_readme_first(package_dir, app_version())


def make_zip(package_dir: Path, zip_path: Path, root_name: str) -> None:
    """Spakuj katalog paczki (z katalogiem najwyższego poziomu ``root_name``)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, f"{root_name}/{path.relative_to(package_dir).as_posix()}")


def verify_zip(zip_path: Path) -> List[str]:
    """Sprawdź, czego w paczce być nie powinno. Zwraca listę problemów.

    Sprawdzamy dwie rzeczy:

    * **nazwy** wpisów - zabronione katalogi (``.git``, ``.venv``, ``tmp``,
      ``flights``, ``scenes/user``), pliki ``.pyc`` i ścieżki użytkownika,
    * **treść** plików tekstowych - ale tylko **naszych** plików (kod firm
      trzecich w ``site-packages`` bywa pełen przykładowych ścieżek i nie jest
      naszym wyciekiem). Szukamy konkretnej nazwy użytkownika, który zbudował
      paczkę (``\\Users\\<nazwa>\\``), a nie dowolnego ``C:\\Users`` - dokumentacja
      używa placeholderów typu ``C:\\Users\\x\\...``, co jest poprawne.
    """
    problems: List[str] = []
    forbidden_names = (".git/", ".venv/", "/tmp/", "/flights/", "scenes/user/",
                       ".pytest_cache/", "docs/ref/")
    user_name = Path.home().name.lower()
    #: tylko PRAWDZIWA nazwa użytkownika budującego paczkę = wyciek
    real_markers = (f"users\\{user_name}\\", f"users/{user_name}/",
                    f"{user_name}\\appdata", f"{user_name}/appdata")
    text_suffixes = (".py", ".txt", ".md", ".json", ".bat", ".css", ".js",
                     ".html", ".toml", ".cfg", ".ini")
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            lowered = name.lower()
            if name.endswith((".pyc", ".pyo")):
                problems.append(f"skompilowany plik: {name}")
            for token in forbidden_names:
                if token in lowered:
                    problems.append(f"zabroniona ścieżka {token}: {name}")
            if "/users/" in lowered or "\\users\\" in lowered:
                problems.append(f"ścieżka użytkownika w nazwie: {name}")
            if "site-packages/" in lowered or "site-packages\\" in lowered:
                continue                     # kod firm trzecich - nie nasz wyciek
            if not (info.file_size and info.file_size < 2_000_000
                    and name.endswith(text_suffixes)):
                continue
            text = archive.read(info).decode("utf-8", "ignore").lower()
            for marker in real_markers:
                if marker in text:
                    problems.append(f"nazwa użytkownika w treści: {name}")
                    break
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Buduje paczkę przenośną dla Windows")
    parser.add_argument("--version", default=None,
                        help="wersja w nazwie pliku (domyślnie app/__init__.py)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="katalog wynikowy")
    parser.add_argument("--keep", action="store_true",
                        help="zostaw rozpakowany katalog roboczy (diagnostyka)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    version = args.version or app_version()
    started = time.perf_counter()
    root_name = f"DroneSim-portable-{version}-win64"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{root_name}.zip"

    (ROOT / "tmp").mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="portable_build_", dir=str(ROOT / "tmp")))
    package_dir = work / root_name
    try:
        _print(f"wersja aplikacji: {version}, dronemoves: {dronemoves_version()}")
        embedded = fetch_embedded_python()
        assemble(package_dir, embedded)
        _print("pakuję ZIP…")
        make_zip(package_dir, zip_path, root_name)
        problems = verify_zip(zip_path)
        if problems:
            for problem in problems:
                print(f"  BŁĄD: {problem}", file=sys.stderr)
            raise SystemExit(f"paczka zawiera {len(problems)} niedozwolonych elementów")
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        _print(f"gotowe: {zip_path} ({size_mb:.1f} MB, "
               f"{time.perf_counter() - started:.0f} s)")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            _print(f"katalog roboczy zostawiony: {work}")


if __name__ == "__main__":
    raise SystemExit(main())
