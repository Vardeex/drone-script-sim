"""Pomocnicze funkcje testów niezależne od platformy (bez psutil)."""

from __future__ import annotations

import os


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
