"""Pomocnicze funkcje testów niezależne od platformy (bez psutil).

Zasada dla procesów uruchamianych w testach (serwer uvicorn, helper watchdoga):

* na POSIX ``start_new_session=True`` - proces dostaje **własną grupę**
  (``setsid``), więc ``os.killpg`` trafia tylko w niego i jego potomków,
* na Windows ``CREATE_NEW_PROCESS_GROUP`` + ``taskkill /T /F /PID``.

Bez tego ``os.killpg(os.getpgid(pid), SIGTERM)`` zabijał **całą grupę pytest**
(krok CI kończył się „The operation was canceled” mimo zielonych testów).
:func:`kill_tree` dodatkowo sprawdza, czy grupa procesu nie jest grupą
bieżącego procesu - wtedy zabija tylko proces (``terminate()``).
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any, Dict


def child_process_kwargs() -> Dict[str, Any]:
    """Argumenty ``Popen``, które dają procesowi własną grupę/sesję."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def spawn(args, **kwargs: Any) -> subprocess.Popen:
    """Uruchom proces w osobnej grupie (``spawn`` = ``subprocess.Popen`` + grupa)."""
    params = child_process_kwargs()
    params.update(kwargs)
    return subprocess.Popen(args, **params)  # noqa: S603 - argumenty podaje test


def owns_own_group(pid: int) -> bool:
    """Czy ``pid`` jest w **innej** grupie niż bieżący proces (POSIX).

    Na Windows grupa procesów ma inne znaczenie (``taskkill /T`` działa po
    drzewie PID), więc funkcja zwraca tam ``False`` - nie używamy ``killpg``.
    """
    if os.name == "nt":
        return False
    try:
        return os.getpgid(pid) != os.getpgid(0)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        return False


def kill_tree(process: subprocess.Popen, timeout: float = 10.0) -> None:
    """Zatrzymaj proces **wraz z potomkami**, ale nigdy własnej grupy pytest.

    :param process: proces uruchomiony przez :func:`spawn` (albo dowolny inny)
    :param timeout: ile sekund czekać na zakończenie przed ``kill()``
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, check=False)
    elif owns_own_group(process.pid):
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            process.terminate()
    else:
        # proces dzieli grupę z pytest - killpg zabiłby cały krok CI
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:      # pragma: no cover - bardzo rzadkie
            pass


def pid_alive(pid: int) -> bool:
    """Czy proces o danym PID żyje (POSIX: ``os.kill(pid, 0)``, Windows: ``OpenProcess``)."""
    if os.name == "nt":  # pragma: no cover - sprawdzane na Windows w CI
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:      # proces istnieje, ale jest innego użytkownika
        return True
    except OSError:
        return False
