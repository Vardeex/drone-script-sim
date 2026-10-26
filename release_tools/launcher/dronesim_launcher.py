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
import itertools
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


class _NotifyIconIdentifier(ctypes.Structure):
    """``NOTIFYICONIDENTIFIER`` - identyfikacja ikony dla ``Shell_NotifyIconGetRect``."""

    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("guidItem", _Guid)]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              wintypes.WPARAM, wintypes.LPARAM)


class _WndClass(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


#: Stały GUID ikony. Bez niego system rozpoznaje ikonę po parze (hwnd, uID),
#: a hwnd jest inny przy każdym uruchomieniu - Windows traktuje wtedy ikonę jak
#: nową i wrzuca ją do „ukrytych ikon”, zapominając wyboru użytkownika.
TRAY_GUID_TEXT = "{A3D6C1E2-4B7F-4C58-9E1A-2F0B6D8C7A31}"


def guid_from_text(text: str) -> _Guid:
    """Zamień GUID w postaci tekstowej na strukturę Win32 (kolejność little-endian)."""
    raw = uuid.UUID(text).bytes_le
    data4 = (ctypes.c_ubyte * 8)(*raw[8:16])
    return _Guid(int.from_bytes(raw[0:4], "little"),
                 int.from_bytes(raw[4:6], "little"),
                 int.from_bytes(raw[6:8], "little"), data4)


def tray_action(event: int) -> Optional[str]:
    """Co zrobić po zdarzeniu ikony: ``"open"``, ``"menu"`` albo ``None``.

    Wersja 4 powiadomień (``NOTIFYICON_VERSION_4``) przysyła w ``lParam`` zdarzenia
    ``NIN_SELECT`` / ``NIN_KEYSELECT`` / ``WM_CONTEXTMENU``; starsze wersje
    przysyłają komunikaty myszy (``WM_LBUTTONUP`` itd.). Obsługujemy oba warianty:
    lewy przycisk otwiera aplikację, prawy (i menu z klawiatury) pokazuje menu.
    """
    if event in (TrayIcon.NIN_SELECT, TrayIcon.WM_LBUTTONUP,
                 TrayIcon.WM_LBUTTONDBLCLK):
        return "open"
    if event in (TrayIcon.NIN_KEYSELECT, TrayIcon.WM_CONTEXTMENU,
                 TrayIcon.WM_RBUTTONUP):
        return "menu"
    return None


def tray_menu_items() -> List[Tuple[int, Optional[str]]]:
    """Pozycje menu ikony: ``(id, tekst)``; ``None`` = separator."""
    return [(TrayIcon.ID_OPEN, "Otwórz DroneSim"),
            (0, None),
            (TrayIcon.ID_QUIT, "Zakończ DroneSim")]


#: licznik instancji ikony - każda potrzebuje własnej nazwy klasy okna
_TRAY_CLASS_COUNTER = itertools.count(1)


class TrayIcon:
    """Ikona w zasobniku z menu „Otwórz DroneSim” / „Zakończ DroneSim”.

    Czyste Win32 (ctypes), bez zależności. Ważne szczegóły, bez których menu
    bywa niewidoczne na Windows 11:

    * **prototypy funkcji** - bez ``argtypes`` ctypes obcina uchwyty (HMENU/HWND)
      do 32 bitów, więc ``TrackPopupMenu`` dostawał nieprawidłowy uchwyt menu;
    * **``NOTIFYICON_VERSION_4``** (``NIM_SETVERSION``) - poprawne kotwiczenie
      menu, zdarzenia ``NIN_SELECT``/``WM_CONTEXTMENU``;
    * **``SetForegroundWindow`` + ``PostMessage(WM_NULL)``** przed/po
      ``TrackPopupMenu`` - inaczej menu nie pojawia się albo nie znika;
    * **``NIF_GUID``** ze stałym GUID - system pamięta ustawienie „pokaż ikonę”;
    * **``TaskbarCreated``** - po restarcie Eksploratora ikona jest dodawana
      ponownie (wcześniej znikała na zawsze).
    """

    WM_TRAY = 0x8000 + 1
    WM_COMMAND = 0x0111
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    WM_NULL = 0x0000
    WM_CONTEXTMENU = 0x007B
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    NIN_SELECT, NIN_KEYSELECT = 0x0400, 0x0401
    NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_STATE = 0x01, 0x02, 0x04, 0x08
    NIF_GUID = 0x20
    NIS_HIDDEN = 0x01
    NOTIFYICON_VERSION_4 = 4
    MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
    TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
    ID_OPEN, ID_QUIT = 1001, 1002

    def __init__(self, tooltip: str, icon_path: Optional[Path] = None) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._declare_prototypes()
        self.tooltip = tooltip[:127]
        self.on_open = None
        self.on_quit = None
        self.hwnd = None
        self._icon_path = icon_path
        self._hicon = None
        self._data = None
        self._guid = guid_from_text(TRAY_GUID_TEXT)
        self._use_guid = True
        self._version4 = False
        self._stop_requested = False
        self.taskbar_created = 0
        self._proc = _WNDPROC(self._wndproc)      # trzymamy referencję (GC!)
        # nazwa klasy musi być unikalna w procesie (testy tworzą kilka ikon)
        self.class_name = (f"DroneSimLauncher{os.getpid()}"
                           f"_{next(_TRAY_CLASS_COUNTER)}")

    def _declare_prototypes(self) -> None:
        """Ustaw typy argumentów i wyników - inaczej ctypes obcina uchwyty.

        Bez ``argtypes`` ctypes traktuje każdy argument jako 32-bitowy ``int``,
        więc 64-bitowe uchwyty (HMENU, HWND) są obcinane. Skutek: ``TrackPopupMenu``
        dostawał nieprawidłowy uchwyt menu i menu ikony **w ogóle się nie pokazywało**.
        """
        u, s, k = self.user32, self.shell32, self.kernel32
        u.RegisterClassW.argtypes = [ctypes.c_void_p]
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                      wintypes.HMENU, wintypes.HINSTANCE,
                                      ctypes.c_void_p]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.DestroyWindow.restype = wintypes.BOOL
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                  wintypes.UINT, wintypes.UINT]
        u.GetMessageW.restype = ctypes.c_int
        u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t
        u.PostQuitMessage.argtypes = [ctypes.c_int]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
        u.PostMessageW.restype = wintypes.BOOL
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.restype = wintypes.BOOL
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                                  wintypes.LPCWSTR]
        u.AppendMenuW.restype = wintypes.BOOL
        u.DestroyMenu.argtypes = [wintypes.HMENU]
        u.DestroyMenu.restype = wintypes.BOOL
        u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                     ctypes.c_void_p]
        u.TrackPopupMenu.restype = wintypes.BOOL
        u.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        u.GetCursorPos.restype = wintypes.BOOL
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.LoadImageW.restype = wintypes.HANDLE
        u.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        u.LoadIconW.restype = wintypes.HICON
        u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        u.RegisterWindowMessageW.restype = wintypes.UINT
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u.PeekMessageW.restype = wintypes.BOOL
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowW.restype = wintypes.HWND
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        s.Shell_NotifyIconW.argtypes = [wintypes.DWORD,
                                        ctypes.POINTER(_NotifyIconData)]
        s.Shell_NotifyIconW.restype = wintypes.BOOL
        s.Shell_NotifyIconGetRect.argtypes = [ctypes.POINTER(_NotifyIconIdentifier),
                                              ctypes.POINTER(wintypes.RECT)]
        s.Shell_NotifyIconGetRect.restype = ctypes.c_long        # HRESULT
        k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k.GetModuleHandleW.restype = wintypes.HMODULE

    def create(self) -> None:
        """Zarejestruj klasę okna, utwórz ukryte okno i dodaj ikonę do zasobnika."""
        instance = self.kernel32.GetModuleHandleW(None)
        wnd_class = _WndClass()
        wnd_class.lpfnWndProc = self._proc
        wnd_class.hInstance = instance
        wnd_class.lpszClassName = self.class_name
        if not self.user32.RegisterClassW(ctypes.byref(wnd_class)):
            error = ctypes.get_last_error()
            # 1410 = ERROR_CLASS_ALREADY_EXISTS - klasa o tej nazwie już jest
            # (ta sama nazwa w procesie), można jej użyć
            if error != 1410:
                raise OSError(error, "RegisterClassW nie powiódł się")
        self.hwnd = self.user32.CreateWindowExW(
            0, self.class_name, APP_TITLE, 0, 0, 0, 0, 0, None, None, instance, None)
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW nie powiódł się")
        self._hicon = self._load_icon()
        # komunikat wysyłany przez Eksplorator po restarcie paska zadań
        self.taskbar_created = self.user32.RegisterWindowMessageW("TaskbarCreated")
        self.add_icon()

    def add_icon(self) -> None:
        """Dodaj ikonę (z GUID, a gdy shell odmówi - bez GUID) i ustaw wersję 4."""
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        data.uCallbackMessage = self.WM_TRAY
        data.hIcon = self._hicon
        data.szTip = self.tooltip
        if self._use_guid:
            data.uFlags |= self.NIF_GUID
            data.guidItem = self._guid
        if not self.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(data)):
            if self._use_guid:
                # starszy shell albo ikona już zarejestrowana bez GUID
                self._use_guid = False
                self.add_icon()
                return
            raise OSError(ctypes.get_last_error(),
                          "Shell_NotifyIconW(NIM_ADD) nie powiódł się")
        self._data = data
        # Wersja 4: zdarzenia NIN_SELECT/NIN_KEYSELECT/WM_CONTEXTMENU i punkt
        # zakotwiczenia menu w wParam (bez tego menu bywa w złym miejscu).
        version = _NotifyIconData()
        version.cbSize = ctypes.sizeof(_NotifyIconData)
        version.hWnd = self.hwnd
        version.uID = 1
        version.uFlags = self.NIF_GUID if self._use_guid else 0
        if self._use_guid:
            version.guidItem = self._guid
        version.uVersion = self.NOTIFYICON_VERSION_4
        self._version4 = bool(
            self.shell32.Shell_NotifyIconW(self.NIM_SETVERSION, ctypes.byref(version)))
        self.show_icon()

    def show_icon(self) -> None:
        """Poproś shell, żeby ikona była widoczna (nie w „ukrytych ikonach”).

        Windows 11 domyślnie wrzuca nowe ikony do schowka; nie ma API, które
        wymusi ich przypięcie, ale wyzerowanie ``NIS_HIDDEN`` jest prośbą, którą
        shell zwykle spełnia. Stały GUID sprawia, że wybór użytkownika zostaje
        zapamiętany przy kolejnych uruchomieniach.
        """
        data = _NotifyIconData()
        data.cbSize = ctypes.sizeof(_NotifyIconData)
        data.hWnd = self.hwnd
        data.uID = 1
        data.uFlags = self.NIF_STATE | (self.NIF_GUID if self._use_guid else 0)
        if self._use_guid:
            data.guidItem = self._guid
        data.dwState = 0                    # 0 = widoczna
        data.dwStateMask = self.NIS_HIDDEN
        self.shell32.Shell_NotifyIconW(self.NIM_MODIFY, ctypes.byref(data))

    def icon_rect(self) -> Dict[str, object]:
        """Gdzie jest ikona (``Shell_NotifyIconGetRect``) - diagnostyka widoczności."""
        identify = _NotifyIconIdentifier()
        identify.cbSize = ctypes.sizeof(_NotifyIconIdentifier)
        identify.hWnd = self.hwnd
        identify.uID = 1
        if self._use_guid:
            identify.guidItem = self._guid
        rect = wintypes.RECT()
        result = self.shell32.Shell_NotifyIconGetRect(ctypes.byref(identify),
                                                      ctypes.byref(rect))
        return {"hresult": int(result), "found": int(result) == 0,
                "rect": [int(rect.left), int(rect.top),
                         int(rect.right), int(rect.bottom)]}

    def run(self, on_open, on_quit) -> None:
        """Pętla komunikatów - blokuje, dopóki użytkownik nie wybierze „Zakończ”."""
        self.on_open = on_open
        self.on_quit = on_quit
        self.create()
        if self._stop_requested:           # stop() przed utworzeniem okna
            self.destroy()
            return
        try:
            message = wintypes.MSG()
            while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                self.user32.TranslateMessage(ctypes.byref(message))
                self.user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self.destroy()

    def stop(self) -> None:
        """Zamknij pętlę komunikatów i usuń ikonę (``NIM_DELETE`` w ``destroy``).

        Wywoływane przez ``--stop-file``, przez pozycję „Zakończ DroneSim”
        w menu ikony **oraz przez launcher, gdy proces serwera zakończy się
        sam** (np. ``POST /api/shutdown`` z przycisku w aplikacji).
        """
        self._stop_requested = True
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

    def _anchor(self, wparam: int) -> tuple:
        """Punkt zakotwiczenia menu: z ``wParam`` (wersja 4) albo kursor."""
        if self._version4:
            x = ctypes.c_short(wparam & 0xFFFF).value
            y = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            if x or y:
                return x, y
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def _show_menu(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Pokaż menu ikony (prawy przycisk myszy albo klawiatura)."""
        if x is None or y is None:
            x, y = self._anchor(0)
        menu = self.user32.CreatePopupMenu()
        if not menu:
            return
        chosen = 0
        try:
            for item_id, label in tray_menu_items():
                if label is None:
                    self.user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None)
                else:
                    self.user32.AppendMenuW(menu, self.MF_STRING, item_id, label)
            # Bez SetForegroundWindow menu nie dostaje fokusu i potrafi w ogóle
            # się nie pokazać; PostMessage(WM_NULL) po zamknięciu jest wymagane,
            # żeby menu zamykało się po kliknięciu poza nim (klasyczna pułapka).
            self.user32.SetForegroundWindow(self.hwnd)
            chosen = self.user32.TrackPopupMenu(
                menu, self.TPM_RIGHTBUTTON | self.TPM_RETURNCMD | self.TPM_NONOTIFY,
                int(x), int(y), 0, self.hwnd, None)
        finally:
            self.user32.DestroyMenu(menu)
            self.user32.PostMessageW(self.hwnd, self.WM_NULL, 0, 0)
        self._command(int(chosen))

    def _command(self, command: int) -> None:
        if command == self.ID_OPEN and self.on_open:
            self.on_open()
        elif command == self.ID_QUIT and self.on_quit:
            self.on_quit()

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == self.WM_TRAY:
            action = tray_action(lparam & 0xFFFF)
            if action == "open":
                if self.on_open:
                    self.on_open()
            elif action == "menu":
                self._show_menu(*self._anchor(wparam))
            return 0
        if message == self.WM_COMMAND:
            self._command(wparam & 0xFFFF)
            return 0
        if self.taskbar_created and message == self.taskbar_created:
            # Eksplorator został zrestartowany - ikona zniknęła z paska, dodaj ją
            self._data = None
            self.add_icon()
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


def shutdown_running(port: int, log: Log) -> int:
    """Zamknij działającą instancję (``--shutdown``, skrót „Zamknij DroneSim”).

    Wysyła ``POST /api/shutdown`` do lokalnego serwera i czeka, aż port zwolni
    się (serwer kończy proces chwilę po odpowiedzi). Gdy program nie działa,
    kończymy się spokojnie kodem 0 - skrót w menu Start nie może wtedy
    pokazywać błędu.
    """
    if not port_open(port):
        log(f"--shutdown: nic nie działa na porcie {port} - nie ma czego zamykać")
        return 0
    url = f"http://127.0.0.1:{port}/api/shutdown"
    request = urllib.request.Request(url, method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", "replace")
        log(f"--shutdown: {url} -> {response.status} {body}")
    except urllib.error.URLError as exc:
        log(f"--shutdown: nie udało się wysłać żądania: {exc}")
        return 3
    except OSError as exc:
        log(f"--shutdown: błąd połączenia: {exc}")
        return 3
    deadline = time.time() + 15
    while time.time() < deadline:
        if not port_open(port):
            log("--shutdown: program zamknięty")
            return 0
        time.sleep(0.2)
    log("--shutdown: port nadal zajęty po 15 s")
    return 3


def probe_menu(tray: TrayIcon, timeout: float = 3.0) -> Dict[str, object]:
    """Pokaż menu ikony i sprawdź, czy naprawdę się pojawiło (diagnostyka).

    ``TrackPopupMenu`` blokuje do wyboru pozycji albo ESC, więc menu otwieramy
    w wątku okna, a osobny wątek szuka okna klasy ``#32768`` (menu podręczne),
    mierzy je i zamyka klawiszem ESC. Zwraca ``menu_shown`` i prostokąt menu.
    """
    found: Dict[str, object] = {"menu_shown": False, "rect": None}
    stop = threading.Event()
    user32 = tray.user32

    def watcher() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            menu = user32.FindWindowW("#32768", None)
            if menu:
                rect = wintypes.RECT()
                if user32.GetWindowRect(menu, ctypes.byref(rect)):
                    found["rect"] = [rect.left, rect.top, rect.right, rect.bottom]
                found["menu_shown"] = True
                time.sleep(0.2)
                user32.PostMessageW(menu, 0x0100, 0x1B, 0)      # WM_KEYDOWN/ESC
                return
            time.sleep(0.05)
        stop.set()

    thread = threading.Thread(target=watcher, name="tray-menu-probe", daemon=True)
    thread.start()
    tray._show_menu(300, 300)                  # blokuje do ESC
    thread.join(timeout=timeout)
    return found


def run_tray_selftest(icon_path: Optional[Path]) -> int:
    """``--tray-selftest``: dodaj ikonę i wypisz, gdzie trafiła (diagnostyka).

    Odpowiada na pytanie „czy ikona jest widoczna na pasku, czy w ukrytych
    ikonach”: ``Shell_NotifyIconGetRect`` zwraca prostokąt ikony, a my
    porównujemy go z obszarem ekranu. Dodatkowo otwiera menu i potwierdza, że
    okno menu rzeczywiście się pojawiło. Wynik trafia na ``stdout`` (UTF-8).
    """
    tray = TrayIcon(f"{APP_TITLE} - test zasobnika", icon_path)
    try:
        tray.create()
        # shell potrzebuje chwili na zarejestrowanie ikony w pasku - pompkujemy
        # komunikaty i pytamy o prostokąt kilka razy
        rect = {"found": False, "hresult": -1, "rect": [0, 0, 0, 0]}
        deadline = time.time() + 2.0
        while time.time() < deadline:
            message = wintypes.MSG()
            while tray.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                tray.user32.TranslateMessage(ctypes.byref(message))
                tray.user32.DispatchMessageW(ctypes.byref(message))
            rect = tray.icon_rect()
            if rect["found"]:
                break
            time.sleep(0.1)
        user32 = tray.user32
        screen = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        inside = False
        if rect["found"]:
            left, top, right, bottom = rect["rect"]
            inside = (right > 0 and bottom > 0 and left < screen[0] and top < screen[1])
        menu = probe_menu(tray)
        print(json.dumps({
            "added": True,
            "use_guid": tray._use_guid,
            "version4": tray._version4,
            "menu_items": [label for _, label in tray_menu_items() if label],
            "screen": list(screen),
            **rect,
            "on_screen": inside,
            "menu_shown": menu["menu_shown"],
            "menu_rect": menu["rect"],
        }, ensure_ascii=False))
        return 0 if rect["found"] and menu["menu_shown"] else 1
    finally:
        tray.destroy()


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
    parser.add_argument("--shutdown", action="store_true",
                        help="zamknij działającą instancję i wyjdź (skrót „Zamknij DroneSim”)")
    parser.add_argument("--tray-selftest", action="store_true",
                        help="dodaj ikonę do zasobnika, wypisz jej położenie i wyjdź")
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
    if args.tray_selftest:
        # diagnostyka ikony nie potrzebuje katalogu danych ani logu
        return run_tray_selftest(_icon_path(root))
    data_dir = resolve_data_dir(args.data_dir, root)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        show_error(f"Nie mogę utworzyć katalogu danych:\n{data_dir}\n\n{exc}")
        return 4
    log = Log(data_dir / "logs")
    log(f"--- start launchera: paczka={root}, dane={data_dir}, port={args.port}")

    if args.shutdown:
        # skrót „Zamknij DroneSim” w menu Start (oraz ręczne ``DroneSim.exe --shutdown``)
        return shutdown_running(args.port, log)

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
            # Zasobnik działa w OSOBNYM wątku, żeby launcher mógł pilnować
            # procesu serwera. Gdy serwer zakończy się sam (np. POST
            # /api/shutdown z przycisku „Zakończ program”), pętla komunikatów
            # musi zostać zamknięta, a ikona usunięta (NIM_DELETE w destroy()).
            # Wcześniej tray.run() blokował do wyboru „Zakończ” w menu ikony,
            # więc DroneSim.exe zostawał w tle razem z ikoną przy zegarze.
            tray = TrayIcon(f"{APP_TITLE} - działa", _icon_path(root))

            def run_tray() -> None:
                try:
                    tray.run(on_open=lambda: open_browser(args.port, log),
                             on_quit=stop_event.set)
                except Exception as exc:        # noqa: BLE001 - nie zabijaj launchera
                    log(f"błąd zasobnika: {exc}")

            tray_thread = threading.Thread(target=run_tray, name="tray", daemon=True)
            tray_thread.start()
            try:
                while not stop_event.is_set() and process.poll() is None:
                    if not tray_thread.is_alive():
                        log("zasobnik zamknięty - kończę launcher")
                        stop_event.set()
                        break
                    time.sleep(0.25)
                if process.poll() is not None:
                    log(f"serwer zakończył się (kod {process.returncode}) "
                        "- zamykam launcher i usuwam ikonę")
                    stop_event.set()
            finally:
                tray.stop()                     # WM_CLOSE -> destroy -> NIM_DELETE
                tray_thread.join(timeout=3)
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
