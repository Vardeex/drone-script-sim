"""Testy ikony w zasobniku (menu „Otwórz DroneSim” / „Zakończ DroneSim”).

Windows 11 gubił ikonę i nie pokazywał menu. Testy pilnują przyczyn:

* brak ``argtypes`` w ctypes obcinał uchwyty (HMENU/HWND) do 32 bitów, więc
  ``TrackPopupMenu`` dostawał nieprawidłowy uchwyt i menu się nie pokazywało,
* brak ``NIM_SETVERSION`` (``NOTIFYICON_VERSION_4``) - złe zdarzenia i punkt
  zakotwiczenia menu,
* brak ``SetForegroundWindow`` + ``PostMessage(WM_NULL)`` wokół
  ``TrackPopupMenu`` - menu nie pojawia się albo nie znika,
* brak ``NIF_GUID`` (stały GUID) - system traktuje ikonę jak nową przy każdym
  uruchomieniu i wrzuca ją do „ukrytych ikon”,
* brak obsługi ``TaskbarCreated`` - po restarcie Eksploratora ikona znikała.

Testy „na żywo” (ukryte okno + ``Shell_NotifyIcon``) są tylko na Windows i nie
wymagają klikania - zdarzenia ikony wysyłamy przez ``PostMessage``.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

import pytest

from release_tools.launcher import dronesim_launcher as launcher

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Win32 tylko na Windows")


# --------------------------------------------------------------- części czyste
def test_guid_from_text_uses_windows_byte_order():
    """GUID musi być w kolejności little-endian, inaczej ikona nie ma tożsamości."""
    guid = launcher.guid_from_text(launcher.TRAY_GUID_TEXT)
    assert guid.Data1 == 0xA3D6C1E2
    assert guid.Data2 == 0x4B7F
    assert guid.Data3 == 0x4C58
    assert list(guid.Data4) == [0x9E, 0x1A, 0x2F, 0x0B, 0x6D, 0x8C, 0x7A, 0x31]


def test_tray_action_maps_both_protocol_versions():
    """Lewy przycisk otwiera aplikację, prawy (i klawiatura) pokazuje menu."""
    tray = launcher.TrayIcon.__dict__
    assert launcher.tray_action(tray["NIN_SELECT"]) == "open"          # v4, lewy
    assert launcher.tray_action(tray["WM_LBUTTONUP"]) == "open"        # v0-v3
    assert launcher.tray_action(tray["WM_LBUTTONDBLCLK"]) == "open"
    assert launcher.tray_action(tray["WM_CONTEXTMENU"]) == "menu"      # v4, prawy
    assert launcher.tray_action(tray["NIN_KEYSELECT"]) == "menu"       # klawiatura
    assert launcher.tray_action(tray["WM_RBUTTONUP"]) == "menu"        # v0-v3
    assert launcher.tray_action(0x9999) is None


def test_tray_menu_has_open_and_quit():
    """Menu zawiera „Zakończ DroneSim” (tego brakowało użytkownikowi)."""
    items = launcher.tray_menu_items()
    labels = [label for _, label in items if label]
    assert labels == ["Otwórz DroneSim", "Zakończ DroneSim"]
    assert any(label is None for _, label in items)          # separator
    assert dict(items)[launcher.TrayIcon.ID_QUIT] == "Zakończ DroneSim"


def test_launcher_parses_shutdown_and_selftest_flags():
    """``--shutdown`` (skrót „Zamknij DroneSim”) i ``--tray-selftest``."""
    args = launcher.parse_args(["--shutdown"])
    assert args.shutdown is True and args.tray_selftest is False
    args = launcher.parse_args(["--tray-selftest"])
    assert args.tray_selftest is True and args.shutdown is False
    assert launcher.parse_args([]).shutdown is False


def test_source_declares_prototypes_and_required_calls():
    """Kontrola źródeł: prototypy Win32 i wszystkie wymagane wywołania."""
    source = (ROOT / "release_tools" / "launcher" /
              "dronesim_launcher.py").read_text(encoding="utf-8")
    for needle in (
        "_declare_prototypes", "TrackPopupMenu.argtypes", "CreatePopupMenu.restype",
        "SetForegroundWindow.argtypes", "PostMessageW.argtypes",
        "NOTIFYICON_VERSION_4", "NIM_SETVERSION", "NIF_GUID", "NIS_HIDDEN",
        "RegisterWindowMessageW(\"TaskbarCreated\")",
        "PostMessageW(self.hwnd, self.WM_NULL, 0, 0)",
        "Shell_NotifyIconGetRect",
    ):
        assert needle in source, needle
    # kolejność: fokus przed menu, „WM_NULL” po menu
    assert source.index("SetForegroundWindow(self.hwnd)") < source.index(
        "chosen = self.user32.TrackPopupMenu")
    assert source.index("chosen = self.user32.TrackPopupMenu") < source.index(
        "PostMessageW(self.hwnd, self.WM_NULL, 0, 0)")


# ------------------------------------------------------------------- na żywo
def _pump(tray, until, timeout: float = 2.0) -> None:
    """Przetwarzaj komunikaty okna, aż ``until()`` zwróci prawdę (albo czas minie)."""
    deadline = time.time() + timeout
    message = wintypes.MSG()
    while time.time() < deadline:
        while tray.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            tray.user32.TranslateMessage(ctypes.byref(message))
            tray.user32.DispatchMessageW(ctypes.byref(message))
        if until():
            return
        time.sleep(0.02)


@WINDOWS
def test_left_click_opens_app():
    """Lewy przycisk ikony (``NIN_SELECT`` i stary ``WM_LBUTTONUP``) otwiera aplikację."""
    opened = []
    tray = launcher.TrayIcon("DroneSim - test")
    tray.on_open = lambda: opened.append("open")
    tray.on_quit = lambda: opened.append("quit")
    tray.create()
    try:
        tray.user32.PostMessageW(tray.hwnd, tray.WM_TRAY, 0, tray.NIN_SELECT)
        _pump(tray, lambda: bool(opened))
        assert opened == ["open"]
        opened.clear()
        tray.user32.PostMessageW(tray.hwnd, tray.WM_TRAY, 0, tray.WM_LBUTTONUP)
        _pump(tray, lambda: bool(opened))
        assert opened == ["open"]
    finally:
        tray.destroy()


@WINDOWS
def test_right_click_shows_menu_at_anchor(monkeypatch):
    """Prawy przycisk (``WM_CONTEXTMENU``) otwiera menu w punkcie z ``wParam``."""
    calls = []
    tray = launcher.TrayIcon("DroneSim - test")
    tray._version4 = True
    monkeypatch.setattr(tray, "_show_menu", lambda x, y: calls.append((x, y)))
    tray.create()
    try:
        anchor = 300 | (400 << 16)          # x=300, y=400 spakowane w wParam
        tray.user32.PostMessageW(tray.hwnd, tray.WM_TRAY, anchor, tray.WM_CONTEXTMENU)
        _pump(tray, lambda: bool(calls))
        assert calls == [(300, 400)]
        calls.clear()
        # stary wariant (bez wersji 4) - punkt bierzemy z kursora
        tray.user32.PostMessageW(tray.hwnd, tray.WM_TRAY, 0, tray.WM_RBUTTONUP)
        _pump(tray, lambda: bool(calls))
        assert len(calls) == 1 and isinstance(calls[0][0], int)
    finally:
        tray.destroy()


@WINDOWS
def test_quit_command_stops_launcher():
    """Wybór „Zakończ DroneSim” (ID_QUIT) woła ``on_quit`` - stop launchera."""
    called = []
    tray = launcher.TrayIcon("DroneSim - test")
    tray.on_quit = lambda: called.append("quit")
    tray.create()
    try:
        tray._command(tray.ID_QUIT)         # ta sama ścieżka co z TrackPopupMenu
        assert called == ["quit"]
        tray._command(tray.ID_OPEN)         # „Otwórz” nie zatrzymuje programu
        assert called == ["quit"]
    finally:
        tray.destroy()


@WINDOWS
def test_tray_icon_is_registered_visible_with_guid():
    """Ikona jest w zasobniku, ma GUID, wersję 4 i leży na ekranie (nie w schowku)."""
    tray = launcher.TrayIcon("DroneSim - test")
    tray.create()
    try:
        assert tray._use_guid is True, "ikona powinna mieć stały GUID"
        assert tray._version4 is True, "brak NOTIFYICON_VERSION_4"
        rect = {}
        deadline = time.time() + 2.0
        while time.time() < deadline:
            _pump(tray, lambda: False, timeout=0.1)
            rect = tray.icon_rect()
            if rect["found"]:
                break
            time.sleep(0.1)
        assert rect["found"] is True, rect
        screen = (tray.user32.GetSystemMetrics(0), tray.user32.GetSystemMetrics(1))
        left, top, right, bottom = rect["rect"]
        assert right > 0 and bottom > 0 and left < screen[0] and top < screen[1], rect
    finally:
        tray.destroy()


@WINDOWS
def test_stop_before_run_skips_message_loop():
    """``stop()`` przed ``run()`` nie zostawia ikony ani blokady."""
    tray = launcher.TrayIcon("DroneSim - test")
    tray.stop()
    started = time.time()
    tray.run(on_open=lambda: None, on_quit=lambda: None)
    assert time.time() - started < 2.0
    assert tray._data is None          # ikona usunięta (NIM_DELETE)
    assert tray.hwnd is None


@WINDOWS
def test_stop_closes_message_loop_and_removes_icon():
    """``stop()`` w trakcie pracy kończy pętlę i usuwa ikonę (NIM_DELETE).

    Dokładnie to robi launcher, gdy proces serwera zakończy się sam - np. po
    ``POST /api/shutdown`` z przycisku „Zakończ program”.
    """
    import threading

    tray = launcher.TrayIcon("DroneSim - test")
    done = threading.Event()

    def run() -> None:
        tray.run(on_open=lambda: None, on_quit=lambda: None)
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.time() + 3
    while time.time() < deadline and tray.hwnd is None:
        time.sleep(0.02)
    assert tray.hwnd, "okno ikony nie powstało"
    assert tray._data is not None, "ikona nie została dodana"

    tray.stop()
    assert done.wait(timeout=3), "pętla komunikatów nie zakończyła się po stop()"
    assert tray._data is None and tray.hwnd is None


def test_launcher_watches_server_process_and_stops_tray():
    """Launcher pilnuje procesu serwera i zamyka zasobnik (regresja 0.4.2).

    Wcześniej ``tray.run()`` blokował do wyboru „Zakończ” w menu ikony, więc po
    ``/api/shutdown`` serwer kończył się, ale ``DroneSim.exe`` dalej działał
    z ikoną przy zegarze.
    """
    source = (ROOT / "release_tools" / "launcher" /
              "dronesim_launcher.py").read_text(encoding="utf-8")
    assert "tray_thread = threading.Thread" in source
    assert "if not tray_thread.is_alive()" in source
    assert "process.poll() is not None" in source
    assert "tray.stop()" in source
    assert "tray_thread.join(timeout=3)" in source
