"""Launcher ``DroneSim.exe`` - uruchamia paczkę przenośną jednym kliknięciem.

Co robi
-------
1. Ustala katalog paczki (obok ``DroneSim.exe``) i katalog danych użytkownika,
2. jeśli serwer już działa na porcie - tylko otwiera przeglądarkę,
3. w przeciwnym razie uruchamia **wbudowanego Pythona** z paczki
   (``python\\python.exe -m uvicorn app.server:app``) bez okna konsoli,
4. czeka na ``/api/health``, otwiera przeglądarkę i pokazuje ikonę w zasobniku
   (menu: „Otwórz”, „Zakończ”),
5. „Zakończ” zatrzymuje serwer **razem z procesami potomnymi** - procesy
   potomne są przypisane do obiektu zadania (Job Object) z flagą
   ``KILL_ON_JOB_CLOSE``, więc nie zostają sieroty nawet po nagłym zamknięciu
   launchera.

Błędy startu trafiają do okienka (MessageBox) i do logu
``%LOCALAPPDATA%\\DroneSim\\logs\\launcher-RRRRMMDD.log``.

Katalog danych
--------------
Kolejność: ``--data-dir`` -> ``DRONESIM_DATA_DIR`` -> ``launcher.json`` obok
``DroneSim.exe`` (pisze go instalator) -> katalog paczki. Dzięki temu wersja
przenośna trzyma dane w swoim katalogu (jak ``start.bat``), a instalowana
w ``%LOCALAPPDATA%\\DroneSim``.

Sterowanie (dla testów i CI)
----------------------------
``--no-browser`` (nie otwieraj przeglądarki), ``--no-tray`` (bez ikony
w zasobniku), ``--stop-file ŚCIEŻKA`` (grzeczne zamknięcie po pojawieniu się
pliku), ``--port N`` (inny port), ``--health-timeout S``.

Uruchomienie ze źródeł (do debugowania)::

    python release_tools/launcher/dronesim_launcher.py --package . --no-tray
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

APP_TITLE = "Drone Script Simulator"
DEFAULT_PORT = 8765
HEALTH_TIMEOUT_S = 90.0
DATA_DIR_ENV = "DRONESIM_DATA_DIR"
#: ścieżka pliku ``--stop-file`` przekazywana serwerowi - przycisk „Zakończ
#: program” (POST /api/shutdown) zapisuje ten plik, a launcher kończy się tak,
#: jak przy normalnym zamknięciu (chowa zasobnik i zatrzymuje procesy potomne)
STOP_FILE_ENV = "DRONESIM_STOP_FILE"
#: plik obok ``DroneSim.exe`` z ustawieniami instalatora (m.in. katalog danych)
LAUNCHER_CONFIG = "launcher.json"
#: ``python.exe`` nie pokazuje okna konsoli
CREATE_NO_WINDOW = 0x08000000


def package_root() -> Path:
    """Katalog paczki: obok ``DroneSim.exe`` (albo katalog repo przy testach)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def read_launcher_config(root: Path) -> Dict[str, str]:
    """Wczytaj ``launcher.json`` (instalator zapisuje tam katalog danych)."""
    path = root / LAUNCHER_CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_data_dir(cli_value: Optional[str], root: Path) -> Path:
    """Katalog danych: ``--data-dir`` > zmienna środowiskowa > ``launcher.json`` > paczka."""
    for candidate in (cli_value, os.environ.get(DATA_DIR_ENV),
                      read_launcher_config(root).get("data_dir")):
        if candidate:
            try:
                return Path(candidate).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
    return root


class Log:
    """Prosty log do pliku (UTF-8, z datą) - działa też bez okna konsoli."""

    def __init__(self, folder: Path) -> None:
        self.path = folder / f"launcher-{datetime.now():%Y%m%d}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass


# --------------------------------------------------------------------- Win32
class _IoCounters(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


class JobObject:
    """Obiekt zadania: zamknięcie uchwytu zabija **całe drzewo** procesów.

    Dzięki temu „Zakończ” (albo zamknięcie launchera) nie zostawia serwera
    i jego procesów potomnych - system robi to za nas.
    """

    def __init__(self) -> None:
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.handle = self.kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW nie powiódł się")
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self.kernel32.SetInformationJobObject(
            self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits), ctypes.sizeof(limits))
        if not ok:
            self.close()
            raise OSError(ctypes.get_last_error(),
                          "SetInformationJobObject nie powiódł się")

    def assign(self, pid: int) -> None:
        """Przypisz proces (i przyszłe procesy potomne) do zadania."""
        process = self.kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # ALL|SET_QUOTA
        if not process:
            raise OSError(ctypes.get_last_error(), f"OpenProcess({pid}) nie powiódł się")
        try:
            if not self.kernel32.AssignProcessToJobObject(self.handle, process):
                raise OSError(ctypes.get_last_error(),
                              "AssignProcessToJobObject nie powiódł się")
        finally:
            self.kernel32.CloseHandle(process)

    def terminate(self) -> None:
        if self.handle:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


def show_error(message: str) -> None:
    """Okienko z błędem (launcher nie ma konsoli)."""
    try:
        ctypes.windll.user32.MessageBoxW(None, message, f"{APP_TITLE} - błąd", 0x10)
    except Exception:                                  # noqa: BLE001 - brak GUI
        pass


# ---------------------------------------------------------------- ikona w tray
class _Guid(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", _Guid),
                ("hBalloonIcon", wintypes.HICON)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class _WndClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class TrayIcon:
    """Ikona w zasobniku z menu „Otwórz” / „Zakończ” (czyste Win32, bez zależności)."""

    WM_TRAY = 0x8000 + 1
    WM_COMMAND = 0x0111
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
    MF_STRING = 0x0000
    TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
    ID_OPEN, ID_QUIT = 1001, 1002

    def __init__(self, tooltip: str, icon_path: Optional[Path] = None) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.tooltip = tooltip[:127]
        self.on_open = None
        self.on_quit = None
        self.hwnd = None
        self._icon_path = icon_path
        self._hicon = None
        self._data = None
        self._proc = _WNDPROC(self._wndproc)      # trzymamy referencję (GC!)
        self.class_name = f"DroneSimLauncher{os.getpid()}"

    def create(self) -> None:
        """Zarejestruj klasę okna i utwórz ukryte okno (bez pokazywania)."""
        instance = self.kernel32.GetModuleHandleW(None)
        wnd_class = _WndClass()
        wnd_class.lpfnWndProc = self._proc
        wnd_class.hInstance = instance
        wnd_class.lpszClassName = self.class_name
        if not self.user32.RegisterClassW(ctypes.byref(wnd_class)):
            raise OSError(ctypes.get_last_error(), "RegisterClassW nie powiódł się")
        self.hwnd = self.user32.CreateWindowExW(
            0, self.class_name, APP_TITLE, 0, 0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW nie powiódł się")
        self._hicon = self._load_icon()
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        data.uCallbackMessage = self.WM_TRAY
        data.hIcon = self._hicon
        data.szTip = self.tooltip
        if not self.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(data)):
            raise OSError(ctypes.get_last_error(),
                          "Shell_NotifyIconW(NIM_ADD) nie powiódł się")
        self._data = data

    def run(self, on_open, on_quit) -> None:
        """Pętla komunikatów - blokuje, dopóki użytkownik nie wybierze „Zakończ”."""
        self.on_open = on_open
        self.on_quit = on_quit
        self.create()
        try:
            message = wintypes.MSG()
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self.destroy()

    def stop(self) -> None:
        """Zamknij pętlę komunikatów (wywoływane np. przez ``--stop-file``)."""
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, self.WM_CLOSE, 0, 0)

    def destroy(self) -> None:
        if self._data is not None:
            self.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._data))
            self._data = None
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None

    def _load_icon(self):
        if self._icon_path and Path(self._icon_path).exists():
            # LR_LOADFROMFILE | LR_DEFAULTSIZE
            icon = self.user32.LoadImageW(None, str(self._icon_path), 1, 0, 0,
                                          0x0010 | 0x0040)
            if icon:
                return icon
        return self.user32.LoadIconW(None, ctypes.c_wchar_p(32512))   # IDI_APPLICATION

    def _show_menu(self) -> None:
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, self.MF_STRING, self.ID_OPEN, "Otwórz")
        self.user32.AppendMenuW(menu, self.MF_STRING, self.ID_QUIT, "Zakończ")
        self.user32.SetForegroundWindow(self.hwnd)
        chosen = self.user32.TrackPopupMenu(
            menu, self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD | self.TPM_NONOTIFY,
            point.x, point.y, 0, self.hwnd, None)
        self.user32.DestroyMenu(menu)
        self._command(chosen)

    def _command(self, command: int) -> None:
        if command == self.ID_OPEN and self.on_open:
            self.on_open()
        elif command == self.ID_QUIT and self.on_quit:
            self.on_quit()

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == self.WM_TRAY:
            event = lparam & 0xFFFF
            if event in (self.WM_LBUTTONUP, self.WM_RBUTTONUP):
                self._show_menu()
            return 0
        if message == self.WM_COMMAND:
            self._command(wparam & 0xFFFF)
            return 0
        if message == self.WM_CLOSE:
            self.user32.DestroyWindow(hwnd)
            return 0
        if message == self.WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)


# ------------------------------------------------------------------- serwer
def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Czy ktoś nasłuchuje na porcie?"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def health_ok(port: int, timeout: float = 1.5) -> bool:
    """Czy pod ``/api/health`` odpowiada nasza aplikacja?"""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace").strip() == "ok"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for_health(port: int, timeout: float, log: Log,
                    should_stop) -> bool:
    """Czekaj na ``/api/health``; ``should_stop()`` pozwala przerwać czekanie."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_ok(port):
            return True
        if should_stop():
            return False
        time.sleep(0.3)
    return False


def app_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def open_browser(port: int, log: Log) -> None:
    """Otwórz przeglądarkę (błąd nie jest krytyczny - serwer działa dalej)."""
    url = app_url(port)
    try:
        webbrowser.open(url)
        log(f"otwarto przeglądarkę: {url}")
    except Exception as exc:                          # noqa: BLE001 - brak przeglądarki
        log(f"nie udało się otworzyć przeglądarki: {exc}")


def python_executable(root: Path) -> Optional[Path]:
    """Interpreter do uruchomienia serwera.

    W paczce to **zawsze** ``python\\python.exe`` obok ``DroneSim.exe``. Gdy
    launcher jest zamrożony (PyInstaller), ``sys.executable`` to on sam -
    uruchomienie go z argumentami ``-m uvicorn`` skończyłoby się rekurencją,
    dlatego poza paczką (tryb dev, ``--package`` na repo) bierzemy
    ``sys.executable`` tylko wtedy, gdy NIE jesteśmy zamrożeni.
    """
    bundled = root / "python" / "python.exe"
    if bundled.exists():
        return bundled
    if not getattr(sys, "frozen", False) and Path(sys.executable).exists():
        return Path(sys.executable)
    return None


def start_server(root: Path, data_dir: Path, port: int, log: Log,
                 stop_file: Optional[str] = None):
    """Uruchom serwer wbudowanym Pythonem (bez okna konsoli) w obiekcie zadania."""
    python = python_executable(root)
    if python is None:
        raise FileNotFoundError(
            f"brak wbudowanego Pythona: {root / 'python' / 'python.exe'}")
    command: List[str] = [str(python), "-m", "uvicorn", "app.server:app",
                          "--host", "127.0.0.1", "--port", str(port)]
    env = dict(os.environ)
    env[DATA_DIR_ENV] = str(data_dir)
    env["PYTHONUTF8"] = "1"                    # polskie znaki w logach serwera
    env["PYTHONIOENCODING"] = "utf-8"
    if stop_file:
        # serwer zapisze ten plik na żądanie POST /api/shutdown
        env[STOP_FILE_ENV] = str(Path(stop_file).resolve())
    env.pop("PYTHONPATH", None)                # serwer ma używać kodu z paczki
    server_log = (data_dir / "logs" / f"server-{datetime.now():%Y%m%d}.log")
    server_log.parent.mkdir(parents=True, exist_ok=True)
    handle = server_log.open("a", encoding="utf-8", buffering=1)
    log(f"start serwera: {' '.join(command)} (log: {server_log})")
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=str(root), env=env,
                               stdout=handle, stderr=subprocess.STDOUT,
                               creationflags=flags)
    job = None
    try:
        job = JobObject()
        job.assign(process.pid)
    except OSError as exc:
        log(f"obiekt zadania niedostępny ({exc}) - sprzątanie po PID")
    return process, job, handle, server_log


def stop_server(process, job, log: Log) -> None:
    """Zatrzymaj serwer i **wszystkie** jego procesy potomne."""
    if job is not None:
        log("zatrzymuję obiekt zadania (serwer + procesy potomne)")
        job.terminate()
        job.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        return
    log("zatrzymuję serwer po PID (bez obiektu zadania)")
    try:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=15,
                       creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"taskkill nie powiódł się: {exc}")
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="DroneSim", description=f"{APP_TITLE} - launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true",
                        help="nie otwieraj przeglądarki (testy/CI)")
    parser.add_argument("--no-tray", action="store_true",
                        help="bez ikony w zasobniku (testy/CI)")
    parser.add_argument("--data-dir", default=None,
                        help="katalog danych użytkownika (loty, sceny, config)")
    parser.add_argument("--package", default=None,
                        help="katalog paczki (domyślnie katalog DroneSim.exe)")
    parser.add_argument("--stop-file", default=None,
                        help="grzeczne zamknięcie po pojawieniu się pliku (testy)")
    parser.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT_S)
    parser.add_argument("--version", action="store_true",
                        help="wypisz wersję i zakończ")
    return parser.parse_args(argv)


def _watch_stop_file(path: Optional[str], stop_event: threading.Event,
                     tray: Optional[TrayIcon], log: Log) -> Optional[threading.Thread]:
    """Wątek testowy: pojawienie się pliku = to samo, co „Zakończ”."""
    if not path:
        return None
    target = Path(path)

    def loop() -> None:
        while not stop_event.is_set():
            if target.exists():
                log(f"plik zatrzymania {target} - zamykam")
                stop_event.set()
                if tray is not None:
                    tray.stop()
                return
            time.sleep(0.2)

    thread = threading.Thread(target=loop, name="stop-file", daemon=True)
    thread.start()
    return thread


def version_text() -> str:
    """Wersja aplikacji z ``app/__init__.py`` (bez importu serwera)."""
    init = package_root() / "app" / "__init__.py"
    try:
        for line in init.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "?"


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.version:
        print(f"{APP_TITLE} {version_text()}")
        return 0

    root = Path(args.package).resolve() if args.package else package_root()
    data_dir = resolve_data_dir(args.data_dir, root)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        show_error(f"Nie mogę utworzyć katalogu danych:\n{data_dir}\n\n{exc}")
        return 4
    log = Log(data_dir / "logs")
    log(f"--- start launchera: paczka={root}, dane={data_dir}, port={args.port}")

    server_py = root / "app" / "server.py"
    if not server_py.exists():
        message = (f"Paczka jest niekompletna - brak {server_py}.\n"
                   "Rozpakuj cały ZIP (nie kopiuj pojedynczych plików).")
        log(message)
        show_error(message)
        return 4

    # 1) Serwer już działa? Wtedy tylko otwieramy przeglądarkę.
    if port_open(args.port):
        if health_ok(args.port):
            log("serwer już działa - otwieram przeglądarkę")
            if not args.no_browser:
                open_browser(args.port, log)
            return 0
        message = (f"Port {args.port} jest zajęty przez inny program.\n"
                   "Zamknij go albo uruchom DroneSim.exe z innym portem.")
        log(message)
        show_error(message)
        return 2

    if python_executable(root) is None:
        message = ("Paczka jest niekompletna - brak wbudowanego Pythona:\n"
                   f"{root / 'python' / 'python.exe'}\n"
                   "Rozpakuj cały ZIP (nie kopiuj pojedynczych plików).")
        log(message)
        show_error(message)
        return 4

    process, job, handle, server_log = start_server(root, data_dir, args.port, log,
                                                    args.stop_file)
    stop_event = threading.Event()
    tray: Optional[TrayIcon] = None
    code = 0
    try:
        _watch_stop_file(args.stop_file, stop_event, tray, log)
        healthy = wait_for_health(args.port, args.health_timeout, log,
                                  lambda: stop_event.is_set() or process.poll() is not None)
        if not healthy:
            code = 3
            tail = _tail(server_log)
            message = (f"Serwer nie odpowiedział w {args.health_timeout:.0f} s.\n"
                       f"Log: {server_log}\n\n{tail}")
            log(message)
            show_error(message)
            return code
        log("serwer gotowy (/api/health = ok)")
        if not args.no_browser:
            open_browser(args.port, log)

        if args.no_tray or os.name != "nt":
            while not stop_event.is_set() and process.poll() is None:
                time.sleep(0.25)
            log("koniec pętli (bez zasobnika)")
        else:
            tray = TrayIcon(f"{APP_TITLE} - działa", _icon_path(root))
            tray.run(on_open=lambda: open_browser(args.port, log),
                     on_quit=stop_event.set)
            log("zamknięto zasobnik")
        return code
    except KeyboardInterrupt:
        log("przerwano z klawiatury")
        return 0
    finally:
        stop_server(process, job, log)
        try:
            handle.close()
        except OSError:
            pass
        log("--- koniec launchera")


def _icon_path(root: Path) -> Optional[Path]:
    """Ikona dla zasobnika (jeśli jest w paczce)."""
    for name in ("dronesim.ico", "assets/dronesim.ico"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _tail(path: Path, lines: int = 15) -> str:
    """Ostatnie linie logu serwera (do okienka błędu)."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


if __name__ == "__main__":
    raise SystemExit(main())
