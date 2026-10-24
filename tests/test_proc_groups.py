"""Regresja CI: sprzątanie serwera w testach nie może zabijać procesu pytest.

Objaw na `ubuntu-latest` (krok „Testy w przeglądarce”): 3 kropki w logu, czyli
wszystkie testy przeszły, a krok kończył się **„The operation was canceled”**.

Przyczyna: fixture uruchamiał ``uvicorn`` przez ``subprocess.Popen`` **bez
``start_new_session=True``**, więc serwer był w tej samej grupie procesów co
pytest i powłoka kroku. Sprzątanie robiło ``os.killpg(os.getpgid(pid), SIGTERM)``
- sygnał trafiał we **wszystkie** procesy grupy, czyli także w pytest i powłokę.

Ten test sprawdza to zachowanie wprost (tylko POSIX - na Windows grupa ma inne
znaczenie, a ``taskkill /T`` działa po drzewie PID).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest

from tests import proc_helpers
from tests.proc_helpers import kill_tree, pid_alive, spawn

#: testy sprawdzające grupy procesów działają tylko na POSIX (na Windows nie ma
#: ``os.getpgid``, a ``taskkill /T`` działa po drzewie PID - tam sprawdzamy
#: tylko argumenty ``Popen``)
posix_only = pytest.mark.skipif(os.name == "nt",
                                reason="grupy procesów: test dotyczy POSIX")


def _ready(base: str, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/api/features", timeout=1)
            return True
        except Exception:                       # noqa: BLE001 - czekamy na start
            time.sleep(0.2)
    return False


@posix_only
def test_stop_server_does_not_kill_pytest():
    """``_stop_server`` zatrzymuje serwer, a proces testu **nadal żyje**.

    Geometria/oczekiwanie jest tu binarne: po sprzątaniu serwer nie odpowiada
    i nie istnieje, a ``os.getpid()`` (pytest) jest nadal aktywne - wcześniej
    ``killpg`` kończył cały proces testowy (dlatego test nie mógłby nawet
    dojść do asercji na Linuxie, gdyby błąd wrócił).
    """
    me = os.getpid()
    assert pid_alive(me)
    # importy tylko dla tego testu: moduł testów przeglądarkowych wymaga
    # Playwrighta, a ten test ma działać także tam, gdzie go nie ma
    from tests.proc_helpers import owns_own_group
    from tests.test_route_planner_browser import _free_port, _stop_server

    my_group = os.getpgid(0)
    port = _free_port()
    process = spawn(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert owns_own_group(process.pid), (
            "serwer nie ma własnej grupy procesów - killpg zabiłby pytest")
        assert os.getpgid(process.pid) != my_group
        assert _ready(f"http://127.0.0.1:{port}"), "serwer nie wystartował"
        _stop_server(process)
    finally:
        kill_tree(process)

    # serwer nie żyje i nie odpowiada
    assert process.poll() is not None, "serwer nadal działa po _stop_server"
    assert not pid_alive(process.pid)
    with pytest.raises(Exception):              # noqa: B017 - dowolny błąd połączenia
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/features", timeout=1)
    # a proces testu nadal żyje (to jest sedno regresji)
    assert pid_alive(me), "sprzątanie zabiło proces pytest"
    assert os.getpgid(0) == my_group


def test_child_process_kwargs_per_platform():
    """Procesy testowe dostają własną grupę/sesję na obu platformach.

    POSIX: ``start_new_session=True`` (``setsid``) - bez tego ``killpg``
    w sprzątaniu zabija grupę pytest (awaria kroku CI na ubuntu).
    Windows: ``CREATE_NEW_PROCESS_GROUP`` - ``taskkill /T`` działa po drzewie PID.
    """
    kwargs = proc_helpers.child_process_kwargs()
    if os.name == "nt":
        assert kwargs.get("creationflags") == subprocess.CREATE_NEW_PROCESS_GROUP
        assert "start_new_session" not in kwargs
        assert proc_helpers.owns_own_group(os.getpid()) is False
    else:  # pragma: no cover - sprawdzane w CI na ubuntu
        assert kwargs == {"start_new_session": True}


def test_kill_tree_cleans_up_child():
    """``kill_tree`` zatrzymuje proces uruchomiony przez ``spawn``."""
    process = spawn([sys.executable, "-c", "import time; time.sleep(60)"])
    assert pid_alive(process.pid)
    kill_tree(process, timeout=10)
    assert process.poll() is not None
    assert not pid_alive(process.pid)


@posix_only
def test_kill_tree_without_own_group_falls_back_to_terminate(monkeypatch):
    """``kill_tree`` nie woła ``killpg``, gdy proces dzieli grupę z pytest.

    Scenariusz z CI: gdyby ``owns_own_group`` zwróciło fałsz (proces w naszej
    grupie), ``kill_tree`` musi użyć ``terminate()`` - ``killpg`` zabiłby cały
    krok. Podstawka ``os.killpg`` **tylko zapisuje** wywołanie (sygnatura jak
    prawdziwej funkcji: ``(pgid, sig)``) i **nie wysyła żadnego sygnału** -
    wcześniejsza wersja wołała prawdziwe ``killpg(..., własna grupa)``, czyli
    na Linuxie zabiłaby proces pytest, zamiast sprawdzić, że nie ma wywołania.
    """
    process = spawn([sys.executable, "-c", "import time; time.sleep(30)"])
    called = []

    def _guard(pgid, sig):
        called.append((pgid, sig))          # zapis tylko - żadnego sygnału

    monkeypatch.setattr(os, "killpg", _guard)
    monkeypatch.setattr(proc_helpers, "owns_own_group", lambda pid: False)
    try:
        proc_helpers.kill_tree(process, timeout=10)
    finally:
        monkeypatch.undo()
        if process.poll() is None:
            kill_tree(process, timeout=10)
    assert called == [], f"killpg wywołane mimo braku własnej grupy: {called}"
    assert process.poll() is not None, "proces nie został zatrzymany"
    assert pid_alive(os.getpid())
    assert os.getpgid(0) == os.getpgid(os.getpid())


@posix_only
def test_killpg_stub_never_sends_real_signal(monkeypatch):
    """Podstawka ``os.killpg`` w teście nie może realnie sygnalizować.

    Sprawdzenie same w sobie: po podmianie ``killpg`` wywołanie z własną grupą
    (tak jak robiła stara wersja ``_guard``) nie kończy procesu testowego,
    a jedynie zostaje zapisane.
    """
    called = []

    def _guard(pgid, sig):
        called.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", _guard)
    os.killpg(os.getpgid(0), 15)            # sygnał NIE idzie do systemu
    assert called == [(os.getpgid(0), 15)]
    assert pid_alive(os.getpid())
