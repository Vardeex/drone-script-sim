"""Runtime sandboxu - uruchamiany w podprocesie ze skryptem użytkownika.

Zadania:
  * utworzyć jeden obiekt :class:`~app.sim.core.Simulation` (stan globalny),
  * podmienić ``time.sleep`` / ``time.time`` / ``time.monotonic`` /
    ``time.perf_counter`` na wirtualny zegar (skrypt wykonuje się błyskawicznie,
    a czas płynie w symulacji),
  * zapisywać strumieniowo telemetrię i zdarzenia do pliku JSONL, aby aplikacja
    mogła je czytać na żywo (UI),
  * przechwycić wyjątek kończący skrypt i zapisać go z numerem linii.

Ten moduł nie zna żadnej biblioteki drona - adaptery podstawiają swoje mocki
na ``sys.path`` (np. ``djitellopy``).
"""

from __future__ import annotations

import inspect
import json
import os
import threading
import time
import traceback
from typing import Any, Dict, Optional

_STATE: Dict[str, Any] = {"sim": None, "log": None, "settings": {}, "script": ""}


def configure(config: Dict[str, Any]) -> None:
    """Zainstaluj hooki sandboxu (wywoływane przez runner przed skryptem)."""
    from app.sim import core

    _STATE["log_path"] = config.get("log_path")
    _STATE["script"] = config.get("script_name", "script.py")
    _STATE["work_dir"] = config.get("work_dir")
    settings = core.Settings()
    for key, value in (config.get("settings") or {}).items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    _STATE["settings"] = settings
    sim = core.Simulation(settings)
    _STATE["sim"] = sim
    _STATE["script_name"] = config.get("script_name", "script.py")
    _STATE["log"] = _LogWriter(_STATE.get("log_path"))
    sim.after_command_hook = _STATE["log"].snapshot

    install_virtual_clock(sim)
    _start_watchdog(config.get("parent_pid"))


def get_sim():
    """Zwróć bieżący obiekt symulacji."""
    return _STATE["sim"]


def get_log() -> "_LogWriter":
    return _STATE["log"]


def _pid_alive(pid: int) -> bool:
    """Czy proces o danym PID żyje (Windows: OpenProcess; POSIX: os.kill)."""
    if os.name == "nt":
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
    try:  # pragma: no cover - POSIX
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _start_watchdog(parent_pid: Optional[int]) -> None:
    """Zabij skrypt, jeśli proces rodzica (serwer) zniknie - ochrona przed sierotami.

    Używamy ORYGINALNEGO ``time.sleep`` (zapisanego przed podmianą na zegar
    wirtualny), bo wirtualny czas stoi, gdy skrypt nic nie robi.
    """
    if not parent_pid:
        return
    real_sleep = _STATE.get("real_sleep") or time.sleep

    def _watch() -> None:
        while True:
            real_sleep(1.0)
            if not _pid_alive(parent_pid):
                os._exit(1)  # serwer zniknął - kończymy bez zostawiania procesu

    threading.Thread(target=_watch, name="dronesim-watchdog", daemon=True).start()


class _LogWriter:
    """Buforowane zapisywanie JSONL (telemetria, zdarzenia)."""

    def __init__(self, path: Optional[str]) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._fh = open(path, "w", encoding="utf-8") if path else None

    def write(self, obj: Dict[str, Any]) -> None:
        if self._fh is None:
            return
        with self._lock:
            self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            with self._lock:
                self._fh.close()
                self._fh = None

    def snapshot(self, sim) -> None:
        """Zapisz zrzut dotychczasowego stanu symulacji (po każdej komendzie)."""
        self.write({
            "type": "snapshot", "now": sim.now,
            "samples": [s.as_dict() for s in sim.recorder.samples],
            "events": [e.as_dict() for e in sim.recorder.events],
            "segments": [sp.motion.as_dict(sp.t0, sp.t1)
                         for sp in sim.recorder.spans if sp.motion is not None],
            "warnings": sim.recorder.warnings, "errors": sim.recorder.errors,
            "stats": sim.stats(),
        })


class VirtualClock:
    """Wirtualny zegar oparty na modelu symulacji (czas symulacji)."""

    def __init__(self, sim) -> None:
        self.sim = sim
        self._offset = sim.now

    def time(self) -> float:
        return self.sim.now

    def monotonic(self) -> float:
        return self.sim.now

    def perf_counter(self) -> float:
        return self.sim.now

    def sleep(self, seconds: float) -> None:
        _sleep_with_rc(seconds)


def install_virtual_clock(sim) -> VirtualClock:
    """Podmień funkcje czasu/snu w module ``time`` na wirtualne.

    Oprócz czasu montujemy też hook integracji RC: jeśli adapter drona wskazał
    aktywny kontroler RC (``rc_provider``), ``time.sleep`` wykonuje ruch RC.
    """
    _STATE.setdefault("real_sleep", time.sleep)
    clock = VirtualClock(sim)
    time.sleep = clock.sleep          # type: ignore[assignment]
    time.time = clock.time            # type: ignore[assignment]
    time.monotonic = clock.monotonic  # type: ignore[assignment]
    time.perf_counter = clock.perf_counter  # type: ignore[assignment]
    return clock


#: funkcja zwracająca aktywny kontroler RC adaptera (ustawiana przy starcie)
_rc_provider = None


def set_rc_provider(provider) -> None:
    """Zarejestruj kontroler RC adaptera (ruch po ``time.sleep``)."""
    global _rc_provider
    _rc_provider = provider


def _rc_controller():
    provider = _rc_provider
    return provider() if provider is not None else None


def _sleep_with_rc(seconds: float) -> None:
    """``time.sleep`` w sandboxie: ruch RC (jeśli aktywny) lub bieg zegara."""
    sim = _STATE.get("sim")
    if sim is None:
        return
    seconds = float(seconds)
    ctrl = _rc_controller()
    if ctrl is not None and seconds > 0:
        ctrl.rc_tick(seconds)
        return
    sim.advance(seconds)


def script_location() -> Dict[str, Any]:
    """Znajdź plik i linię w skrypcie użytkownika (pierwsza ramka poza runtime)."""
    here = os.path.abspath(__file__)
    frame = inspect.currentframe()
    frame = frame.f_back if frame is not None else None
    try:
        while frame is not None:
            filename = os.path.abspath(frame.f_code.co_filename)
            if filename != here and "app" + os.sep + "adapters" not in filename \
                    and filename != os.path.abspath(__file__):
                return {"file": os.path.basename(filename), "line": frame.f_lineno}
            frame = frame.f_back
    finally:
        del frame
    return {"file": _STATE.get("script"), "line": None}


def _sanitize_traceback(text: str, script_name: str) -> str:
    """Usuń prywatne ścieżki: skrypt -> nazwa, projekt -> ścieżka względna, reszta -> <python>."""
    from app import paths

    project = str(paths.PROJECT_ROOT)
    work_dir = _STATE.get("work_dir")
    if work_dir:
        text = text.replace(str(work_dir) + os.sep, "").replace(str(work_dir), "")
    text = text.replace(project + os.sep, "").replace(project, ".")
    lines = []
    for line in text.splitlines():
        if 'File "<string>"' in line:
            continue
        if line.lstrip().startswith(("exec(code", "code = compile")):
            continue
        lines.append(line)
    return "\n".join(lines)


def finish(status: str, exc: Optional[BaseException] = None,
           stdout_tail: str = "", stderr_tail: str = "") -> None:
    """Zapisz podsumowanie lotu do pliku JSONL (wołane przez runner po skrypcie)."""
    sim = _STATE["sim"]
    log = _STATE["log"]
    if sim is None or log is None:
        return
    if exc is not None:
        script_name = _STATE.get("script_name") or "script.py"
        tb_text = _sanitize_traceback(
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), script_name)
        line = _exc_line(exc)
        message = str(exc)
        if _STATE.get("work_dir"):
            message = message.replace(str(_STATE["work_dir"]), "")
        existing = None
        for err in reversed(sim.recorder.errors):
            err_msg = str(err.get("message") or "")
            if err_msg == message or err_msg.endswith(": " + message):
                existing = err
                break
        if existing is not None:
            existing["traceback"] = tb_text
            existing.setdefault("line", line)
        else:
            sim.recorder.add_error(f"{type(exc).__name__}: {exc}", line=line,
                                   file=script_name, type_=type(exc).__name__,
                                   traceback=tb_text)
        status = status or "error"
    data = sim.to_flight_data()
    log.write({
        "type": "summary",
        "status": status,
        "final_state": data.final_state,
        "duration": data.duration,
        "stats": data.stats,
        "warnings": data.warnings,
        "errors": data.errors,
        "samples": data.samples,
        "events": data.events,
        "segments": data.segments,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    })
    log.close()


def _exc_line(exc: BaseException) -> Optional[int]:
    """Numer linii w skrypcie użytkownika, w której powstał wyjątek.

    Dla ``SyntaxError`` / ``IndentationError`` bierzemy ``exc.lineno`` (dotyczy
    skryptu użytkownika); dla wyjątków w czasie wykonania - ostatnią ramkę
    spoza runtimeu i mocków adapterów.
    """
    if isinstance(exc, SyntaxError) and exc.lineno:
        return int(exc.lineno)
    tb = exc.__traceback__
    line = None
    while tb is not None:
        filename = os.path.abspath(tb.tb_frame.f_code.co_filename)
        if "app" + os.sep + "adapters" not in filename \
                and "app" + os.sep + "sim" not in filename \
                and "app" + os.sep + "sandbox_runtime" not in filename \
                and "app" + os.sep + "runner" not in filename:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line
