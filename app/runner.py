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
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .adapters.base import DroneAdapter, get_adapter, detect_adapter
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
    status: str  # ok | error | timeout
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
               work_dir: Optional[Path] = None) -> RunResult:
    """Uruchom skrypt w sandboxie i zwróć wynik lotu.

    :param source: treść skryptu
    :param adapter_id: wybrany adapter (None -> wykryj po importach)
    :param timeout: limit czasu rzeczywistego w sekundach
    :param log_path: ścieżka pliku JSONL (jeśli podana, aplikacja czyta go na żywo)
    :param work_dir: katalog roboczy (domyślnie tymczasowy, usuwany po locie)
    """
    adapter: DroneAdapter = get_adapter(adapter_id) if adapter_id else detect_adapter(source)
    paths.ensure_dirs()

    temp_dir: Optional[tempfile.TemporaryDirectory] = None
    if work_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="dronesim_")
        work_dir = Path(temp_dir.name)
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
        "log_path": str(log_path.resolve()),
        "settings": _build_settings(adapter, extra_settings),
        "rc_provider": getattr(adapter, "rc_provider", None),
        "adapter": adapter.id,
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
    try:
        proc = subprocess.run(
            [venv_python(), "-c", BOOTSTRAP],
            cwd=str(work_dir), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        returncode = proc.returncode
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
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
        stdout=_read_lines(stdout_text),
        stderr=_read_lines(stderr_text),
    )
    if summary is not None:
        flight.status = summary.get("status", "ok")
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
    if temp_dir is not None:
        # skrypt i log są już wczytane do pamięci - sprzątamy katalog tymczasowy
        temp_dir.cleanup()
    return result
