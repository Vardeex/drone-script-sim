"""Uruchamianie skryptu użytkownika w sandboxie (osobny podproces Pythona).

Zabezpieczenia:
  * osobny proces uruchamiany tym samym interpreterem (venv), więc skrypt nie
    może zaszkodzić serwerowi,
  * ``sys.path`` z katalogiem adaptera na początku - ``import djitellopy``
    ładuje mock, nie prawdziwą bibliotekę,
  * blokada sieci: ``socket.socket`` i ``socket.create_connection`` rzucają
    czytelny wyjątek - skrypt nie może wysłać komendy do prawdziwego drona,
  * wirtualny zegar: ``time.sleep``/``time.time``/``time.monotonic``/
    ``time.perf_counter`` są podstawione (czas płynie w symulacji),
  * limit czasu rzeczywistego (standardowo 60 s) - proces jest zabijany,
  * przechwytywanie stdout/stderr z numerem linii.

Skrypt jest wykonywany jako ``__main__`` w kodzie bootstrapu uruchamianym
przez ``python -c``; jego ścieżka trafia do ``sys.argv[0]``.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .adapters.base import DroneAdapter, get_adapter, detect_adapter
from .path_sanitize import sanitize_text as sanitize_paths
from .sim.core import FlightData

DEFAULT_TIMEOUT = 60.0

#: Kod uruchamiany w podprocesie (przed skryptem użytkownika).
BOOTSTRAP = r'''
import json, os, signal, socket, sys, time, traceback

CONFIG = json.loads(os.environ["DRONESIM_CONFIG"])
script = CONFIG["script_path"]
sys.path[:0] = CONFIG["sandbox_paths"]
sys.path.append(CONFIG["project_root"])


class NetworkDisabled(ConnectionError):
    """Blokada sieci w symulatorze."""


MESSAGE = ("Blokada sieci w symulatorze dronów: próba połączenia z %r "
           "została zablokowana. Symulacja nie łączy się z prawdziwym dronem.")


def _blocked(*args, **kwargs):
    target = args[0] if args else "?"
    if hasattr(target, "name"):  # np. AddressFamily.AF_INET przekazany jako socket()
        target = "socket"
    raise NetworkDisabled(MESSAGE % (target,))


class _BlockedSocket:
    def __init__(self, *args, **kwargs):
        _blocked(*args)


_BlockedSocket.connect = _blocked
_BlockedSocket.connect_ex = _blocked
_BlockedSocket.bind = _blocked
_BlockedSocket.sendto = _blocked
socket.socket = _BlockedSocket
socket.create_connection = _blocked
socket.getaddrinfo = _blocked

from app import sandbox_runtime

config = dict(CONFIG)
sandbox_runtime.configure(config)

import importlib
for module_name in CONFIG.get("runtime_modules", []):
    importlib.import_module(module_name)

if CONFIG.get("rc_provider"):
    mod_name, attr = CONFIG["rc_provider"].split(":")
    provider_mod = importlib.import_module(mod_name)
    sandbox_runtime.set_rc_provider(getattr(provider_mod, attr))

status = "ok"
exc = None
try:
    with open(script, "rb") as fh:
        source = fh.read()
    code = compile(source, script, "exec")
    sys.argv = [script]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    globals_dict = {
        "__name__": "__main__", "__file__": script, "__builtins__": __builtins__,
        "__package__": None, "__doc__": None, "__spec__": None,
    }
    exec(code, globals_dict)
except SystemExit as e:
    if e.code not in (0, None):
        status = "error"
        exc = RuntimeError("Skrypt zakończył się przez sys.exit(%r)" % (e.code,))
        traceback.print_exc()
except BaseException as e:
    status = "error"
    exc = e
    traceback.print_exc()
finally:
    try:
        sandbox_runtime.finish(status, exc)
    except Exception:
        traceback.print_exc()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
'''


@dataclass
class RunResult:
    """Wynik uruchomienia skryptu."""

    flight: FlightData
    status: str  # ok | error | timeout | stopped
    stdout: List[Dict[str, Any]] = field(default_factory=list)
    stderr: List[Dict[str, Any]] = field(default_factory=list)
    real_seconds: float = 0.0
    returncode: Optional[int] = None
    log_path: Optional[str] = None


def venv_python() -> str:
    """Interpreter używany do sandboxu (venv, a jeśli brak - bieżący)."""
    candidate = paths.VENV_PYTHON
    if candidate.exists():
        return str(candidate)
    return sys.executable


# --------------------------------------------------- rejestr procesów sandboxu
#: aktywne sesje skryptów: run_id -> RunSession (chronione blokadą)
_SESSIONS: Dict[str, "RunSession"] = {}
_SESSION_LOCK = threading.RLock()


class RunSession:
    """Uruchomienie skryptu: proces + informacja, czy zażądano przerwania."""

    def __init__(self, run_id: str, proc: Optional[subprocess.Popen] = None) -> None:
        self.run_id = run_id
        self.proc = proc
        self.stop_requested = False


def register_process(run_id: str, proc: subprocess.Popen) -> None:
    """Zarejestruj proces skryptu pod identyfikatorem uruchomienia."""
    with _SESSION_LOCK:
        session = _SESSIONS.get(run_id)
        if session is None:
            session = RunSession(run_id)
            _SESSIONS[run_id] = session
        session.proc = proc


def begin_session(run_id: str) -> "RunSession":
    """Utwórz sesję PRZED startem procesu (umożliwia wczesne przerwanie)."""
    session = RunSession(run_id)
    with _SESSION_LOCK:
        _SESSIONS[run_id] = session
    return session


def unregister_process(run_id: str) -> None:
    """Usuń proces z rejestru (po zakończeniu)."""
    with _SESSION_LOCK:
        _SESSIONS.pop(run_id, None)


def active_processes() -> Dict[str, subprocess.Popen]:
    """Kopia rejestru procesów (diagnostyka/testy)."""
    with _SESSION_LOCK:
        return {rid: s.proc for rid, s in _SESSIONS.items() if s.proc is not None}


def _kill_tree(proc: subprocess.Popen) -> None:
    """Zabij proces skryptu wraz z potomnymi (Windows: taskkill /T, POSIX: grupa).

    Uwaga: na Windows ``venv\\Scripts\\python.exe`` to launcher, który uruchamia
    właściwy interpreter jako proces potomny - ``taskkill /T`` zabija oba.

    ``os.killpg`` wolno użyć **tylko** gdy proces ma własną grupę: ``run_script``
    uruchamia go z ``start_new_session=True`` (POSIX) / ``CREATE_NEW_PROCESS_GROUP``
    (Windows). Gdyby ktoś kiedyś podał proces z bieżącej grupy (np. pytest),
    ``killpg`` zabiłby cały proces testowy - dlatego sprawdzamy grupy i w razie
    równości zabijamy tylko ten proces.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:  # pragma: no cover - na Windows nieosiągalne
        try:
            own_group = os.getpgid(proc.pid) != os.getpgid(0)
        except (ProcessLookupError, PermissionError, AttributeError):
            own_group = False
        if own_group:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        else:
            # ta sama grupa co aplikacja - nie wolno zabijać grupy
            proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass


def stop_run(run_id: str) -> bool:
    """Przerwij uruchomienie o danym id. Zwraca True, jeśli proces był aktywny."""
    with _SESSION_LOCK:
        session = _SESSIONS.get(run_id)
        if session is None or session.proc is None or session.proc.poll() is not None:
            return False
        session.stop_requested = True
        proc = session.proc
    _kill_tree(proc)
    return True


def stop_all() -> int:
    """Zabij wszystkie aktywne procesy skryptów (wywoływane przy zamknięciu serwera)."""
    with _SESSION_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    killed = 0
    for session in sessions:
        proc = session.proc
        if proc is not None and proc.poll() is None:
            session.stop_requested = True
            _kill_tree(proc)
            killed += 1
    return killed


def running_script_pids() -> set:
    """PID-y żywych procesów skryptów (diagnostyka/testy)."""
    with _SESSION_LOCK:
        return {p.pid for p in (s.proc for s in _SESSIONS.values())
                if p is not None and p.poll() is None}


def _sanitize_output(text: str, work_dir: Path) -> str:
    """Usuń prywatne ścieżki ze strumieni skryptu.

    Katalog roboczy zniknie całkiem, ścieżki **wewnątrz projektu** zostają jako
    względne (``app/...``), a ścieżki **spoza projektu** - jako sama nazwa pliku
    (np. katalog tymczasowy systemu). Reguły: :mod:`app.path_sanitize`.
    """
    text = text.replace(str(work_dir) + os.sep, "").replace(str(work_dir), "")
    text = sanitize_paths(text)
    # ramka wewnętrznego bootstrapu runnera nie jest częścią skryptu użytkownika
    skipped = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if 'File "<string>"' in line:
            # pomiń tę ramkę i linię kodu, która po niej następuje
            skipped.append(index)
            skipped.append(index + 1)
    return "\n".join(line for i, line in enumerate(lines) if i not in skipped)


def _read_lines(text: str, limit: int = 2000) -> List[Dict[str, Any]]:
    """Podziel strumień na wiersze (zachowaj informację o obcięciu)."""
    lines = text.splitlines()
    result = [{"n": i + 1, "text": line} for i, line in enumerate(lines[:limit])]
    if len(lines) > limit:
        result.append({"n": limit + 1, "text": f"... (obcięto {len(lines) - limit} wierszy)"})
    return result


def read_live_log(log_path: Path) -> Dict[str, Any]:
    """Przeczytaj bieżący stan pliku JSONL (ostatni snapshot lub summary)."""
    state: Dict[str, Any] = {"snapshot": None, "summary": None}
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") in ("snapshot", "summary"):
                    state[item["type"]] = item
    except FileNotFoundError:
        pass
    return state


def _build_settings(adapter: DroneAdapter,
                    extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Zbierz parametry silnika: domyślne + adapter + nadpisania."""
    from .sim.core import Settings

    allowed = set(Settings.__dataclass_fields__.keys())
    settings: Dict[str, Any] = {"accel": False}
    settings.update(adapter.settings())
    settings.update(extra or {})
    return {k: v for k, v in settings.items() if k in allowed}


def run_script(source: str, script_name: str = "script.py",
               adapter_id: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT,
               log_path: Optional[Path] = None,
               extra_settings: Optional[Dict[str, Any]] = None,
               work_dir: Optional[Path] = None,
               run_id: Optional[str] = None) -> RunResult:
    """Uruchom skrypt w sandboxie i zwróć wynik lotu.

    :param source: treść skryptu
    :param adapter_id: wybrany adapter (None -> wykryj po importach)
    :param timeout: limit czasu rzeczywistego w sekundach
    :param log_path: ścieżka pliku JSONL (jeśli podana, aplikacja czyta go na żywo)
    :param work_dir: katalog roboczy (domyślnie ``flights/_work/<run_id>``
        w projekcie - nic nie trafia do katalogu tymczasowego systemu)
    :param run_id: identyfikator do rejestru procesów (pozwala przerwać przez
        :func:`stop_run`); None -> identyfikator wewnętrzny
    """
    adapter: DroneAdapter = get_adapter(adapter_id) if adapter_id else detect_adapter(source)
    paths.ensure_dirs()
    run_id = run_id or f"local-{uuid.uuid4().hex[:8]}"

    # katalog roboczy w projekcie (nadpisuje TEMP podprocesu) - brak śladów na C:
    own_work_dir = work_dir is None
    if own_work_dir:
        work_dir = paths.UPLOADS_DIR / run_id
    work_dir.mkdir(parents=True, exist_ok=True)
    script_path = work_dir / (script_name or "script.py")
    script_path.write_text(source, encoding="utf-8")

    if log_path is None:
        log_path = work_dir / "live.jsonl"
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    sandbox = adapter.prepare_sandbox(FlightData(), None, {})  # type: ignore[arg-type]
    config = {
        "script_path": str(script_path.resolve()),
        "script_name": script_path.name,
        "sandbox_paths": sandbox["sandbox_paths"],
        "runtime_modules": sandbox["runtime_modules"],
        "project_root": str(paths.PROJECT_ROOT),
        "work_dir": str(work_dir.resolve()),
        "log_path": str(log_path.resolve()),
        "settings": _build_settings(adapter, extra_settings),
        "rc_provider": getattr(adapter, "rc_provider", None),
        "adapter": adapter.id,
        "parent_pid": os.getpid(),
    }

    env = dict(os.environ)
    env["DRONESIM_CONFIG"] = json.dumps(config, ensure_ascii=False)
    env["PYTHONPATH"] = str(paths.PROJECT_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["TEMP"] = str(work_dir)
    env["TMP"] = str(work_dir)

    started = time.perf_counter()
    status = "ok"
    returncode: Optional[int] = None
    stdout_text = ""
    stderr_text = ""
    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:  # pragma: no cover
        popen_kwargs["start_new_session"] = True
    session = begin_session(run_id)
    proc = subprocess.Popen(
        [venv_python(), "-c", BOOTSTRAP],
        cwd=str(work_dir), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", **popen_kwargs,
    )
    session.proc = proc
    try:
        try:
            stdout_text, stderr_text = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            status = "timeout"
            _kill_tree(proc)
            try:
                # po zabiciu drzewa odbiór wyjścia MUSI mieć limit: gdy proces
                # potomny przeżyje (np. POSIX bez prawa do zabicia), gołe
                # ``communicate()`` wisiałoby w nieskończoność i test/CI stanął
                stdout_text, stderr_text = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_text, stderr_text = "", ""
        returncode = proc.returncode
        if session.stop_requested:
            status = "stopped"
    finally:
        unregister_process(run_id)
    real_seconds = time.perf_counter() - started

    state = read_live_log(log_path)
    summary = state.get("summary")
    snapshot = state.get("snapshot")
    data = summary or snapshot or {}

    flight = FlightData(
        script_name=script_path.name,
        adapter=adapter.id,
        duration=float(data.get("duration") or (data.get("stats") or {}).get("duration_s") or 0.0),
        samples=data.get("samples") or [],
        events=data.get("events") or [],
        warnings=data.get("warnings") or [],
        errors=data.get("errors") or [],
        segments=data.get("segments") or [],
        script_source=source,
        limits=adapter.limits(),
        stats=data.get("stats") or {},
        final_state=data.get("final_state", "unknown"),
        stdout=_read_lines(_sanitize_output(stdout_text, work_dir)),
        stderr=_read_lines(_sanitize_output(stderr_text, work_dir)),
    )
    if summary is not None:
        flight.status = summary.get("status", "ok")
    if status == "stopped":
        flight.status = "stopped"
        flight.errors.append({
            "message": "Skrypt przerwany ręcznie (przycisk Stop).",
            "line": None, "file": script_path.name, "type": "StoppedError",
        })
    if status == "timeout":
        flight.status = "timeout"
        flight.errors.append({
            "message": f"Przekroczono limit czasu wykonania skryptu ({timeout:.0f} s). "
                       "Proces został zatrzymany.",
            "line": None, "file": script_path.name, "type": "TimeoutError",
        })
        flight.duration = max(flight.duration, float(data.get("now") or 0.0),
                              float((data.get("stats") or {}).get("duration_s") or 0.0))
    elif flight.status == "ok" and returncode not in (0, None) and not flight.errors:
        flight.status = "error"
        flight.errors.append({
            "message": f"Proces skryptu zakończył się kodem {returncode}.",
            "line": None, "file": script_path.name, "type": "ProcessError",
        })

    result = RunResult(
        flight=flight, status=flight.status, stdout=flight.stdout,
        stderr=flight.stderr, real_seconds=round(real_seconds, 3),
        returncode=returncode, log_path=str(log_path),
    )
    flight.planned_trail = _load_planned_trail(work_dir)
    if own_work_dir:
        # skrypt i log są już wczytane do pamięci - sprzątamy katalog roboczy
        shutil.rmtree(work_dir, ignore_errors=True)
    return result


def _load_planned_trail(work_dir: Path) -> list:
    """Wczytaj zaplanowaną trajektorię manewrów zapisaną przez bibliotekę dronemoves.

    Biblioteka (w symulatorze) zapisuje plan do ``dronemoves_plan.json`` w katalogu
    roboczym skryptu. Format tolerancyjny - przy błędzie zwracamy pustą listę.
    """
    path = work_dir / "dronemoves_plan.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    points = data.get("points") if isinstance(data, dict) else data
    if not isinstance(points, list):
        return []
    trail = []
    for item in points:
        if not isinstance(item, dict):
            continue
        try:
            trail.append({
                "x": float(item.get("x", 0.0)),
                "y": float(item.get("y", 0.0)),
                "z": float(item.get("z", 0.0)),
                "t": float(item.get("t", 0.0)),
                "label": str(item.get("label") or ""),
            })
        except (TypeError, ValueError):
            continue
    return trail
