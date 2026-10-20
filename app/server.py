"""Serwer aplikacji Drone Script Simulator (FastAPI, tylko 127.0.0.1).

Endpointy:
  GET  /                       - interfejs webowy
  GET  /api/adapters           - lista adapterów dronów + limity
  GET  /api/examples           - lista przykładowych skryptów
  GET  /api/examples/{name}    - treść przykładu
  POST /api/run                - uruchom skrypt (JSON: source/adapter)
  POST /api/upload             - uruchom wgrany plik .py (multipart)
  GET  /api/run/live/{id}      - bieżący stan uruchomienia (do podglądu na żywo)
  GET  /api/flights            - historia lotów
  GET  /api/flights/{id}       - pełny lot (JSON)
  GET  /api/flights/{id}/csv   - eksport telemetrii do CSV
  POST /api/flights/import     - import lotu z pliku JSON
  DELETE /api/flights/{id}     - usuń lot
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import paths, runner, storage
from .adapters.base import detect_adapter, get_adapter, list_adapters

app = FastAPI(title="Drone Script Simulator", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(paths.STATIC_DIR)), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Aplikacja lokalna: statyki bez cache, żeby zmiany w JS/CSS były natychmiast widoczne."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

#: aktywne uruchomienia (log na żywo): id -> informacje
RUNS: Dict[str, Dict[str, Any]] = {}
MAX_SCRIPT_BYTES = 512 * 1024


class RunRequest(BaseModel):
    """Treść żądania uruchomienia skryptu."""

    source: str = Field(..., description="Kod skryptu Pythona")
    adapter: Optional[str] = Field(None, description="Id adaptera drona (None = autodetekcja)")
    script_name: str = Field("script.py", max_length=120)
    timeout: float = Field(runner.DEFAULT_TIMEOUT, ge=1, le=300)
    accel: bool = Field(False, description="Model ruchu z rampą przyspieszenia")
    save: bool = Field(True, description="Zapisz lot w historii")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(str(paths.STATIC_DIR / "index.html"))


@app.get("/api/adapters")
def api_adapters() -> List[Dict[str, Any]]:
    """Adaptery dronów dostępne w symulatorze."""
    return [info.__dict__ for info in list_adapters()]


@app.get("/api/examples")
def api_examples() -> List[Dict[str, Any]]:
    """Lista przykładowych skryptów (z katalogu examples/)."""
    result = []
    if paths.EXAMPLES_DIR.exists():
        for file in sorted(paths.EXAMPLES_DIR.glob("*.py")):
            result.append({"name": file.name, "size": file.stat().st_size})
    return result


@app.get("/api/examples/{name}")
def api_example(name: str) -> Dict[str, Any]:
    """Treść przykładowego skryptu."""
    file = (paths.EXAMPLES_DIR / name)
    if not file.name.endswith(".py") or not paths.is_within(file, paths.EXAMPLES_DIR) \
            or not file.exists():
        raise HTTPException(404, "Nie znaleziono przykładu.")
    return {"name": file.name, "source": file.read_text(encoding="utf-8")}


# ----------------------------------------------------------------- uruchamianie
def _start_run(source: str, script_name: str, adapter: Optional[str], timeout: float,
               accel: bool, save: bool) -> Dict[str, Any]:
    """Uruchom skrypt w tle i zwróć identyfikator uruchomienia."""
    if len(source.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise HTTPException(413, "Skrypt jest za duży (limit 512 KB).")
    paths.ensure_dirs()
    run_id = f"{time.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    log_path = paths.UPLOADS_DIR / f"{run_id}.jsonl"
    adapter_obj = get_adapter(adapter) if adapter else detect_adapter(source)
    info: Dict[str, Any] = {
        "id": run_id, "status": "running", "started": time.time(),
        "adapter": adapter_obj.id, "script_name": script_name,
        "log_path": str(log_path), "flight_id": None, "error": None,
        "real_seconds": 0.0, "stdout": [], "stderr": [],
    }
    RUNS[run_id] = info

    def _task() -> None:
        try:
            result = runner.run_script(
                source, script_name=script_name, adapter_id=adapter_obj.id,
                timeout=timeout, log_path=log_path, extra_settings={"accel": accel},
            )
            info["stdout"] = result.flight.stdout
            info["stderr"] = result.flight.stderr
            info["real_seconds"] = result.real_seconds
            if save:
                payload = storage.save(result.flight, real_seconds=result.real_seconds)
                info["flight_id"] = payload["id"]
            info["status"] = "done"
        except Exception as exc:  # błąd serwera - zgłoś w odpowiedzi live
            info["status"] = "failed"
            info["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                if Path(info["log_path"]).exists():
                    Path(info["log_path"]).unlink()
            except OSError:
                pass

    import threading

    thread = threading.Thread(target=_task, name=f"run-{run_id}", daemon=True)
    thread.start()
    return {"id": run_id, "status": "running", "adapter": adapter_obj.id}


@app.post("/api/run")
async def api_run(request: RunRequest) -> Dict[str, Any]:
    """Uruchom skrypt podany w treści żądania."""
    if not request.source.strip():
        raise HTTPException(400, "Pusty skrypt.")
    if request.adapter and request.adapter not in [a.id for a in list_adapters()]:
        raise HTTPException(400, f"Nieznany adapter: {request.adapter}")
    return _start_run(request.source, request.script_name or "script.py",
                      request.adapter, request.timeout, request.accel, request.save)


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...),
                     adapter: Optional[str] = Form(None),
                     timeout: float = Form(runner.DEFAULT_TIMEOUT),
                     accel: bool = Form(False)) -> Dict[str, Any]:
    """Wgraj plik .py i uruchom go w symulacji."""
    if not (file.filename or "").lower().endswith(".py"):
        raise HTTPException(400, "Dozwolone są tylko pliki .py.")
    raw = await file.read()
    if len(raw) > MAX_SCRIPT_BYTES:
        raise HTTPException(413, "Skrypt jest za duży (limit 512 KB).")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "Plik musi być w kodowaniu UTF-8.")
    name = Path(file.filename or "script.py").name
    return _start_run(source, name, adapter, timeout or runner.DEFAULT_TIMEOUT, accel, True)


@app.get("/api/run/live/{run_id}")
def api_run_live(run_id: str) -> Dict[str, Any]:
    """Stan uruchomienia: running (z bieżącym snapshotem) lub done (gotowy lot)."""
    info = RUNS.get(run_id)
    if info is None:
        raise HTTPException(404, "Nie znaleziono uruchomienia.")
    response: Dict[str, Any] = {
        "id": run_id, "status": info["status"], "adapter": info["adapter"],
        "script_name": info["script_name"], "error": info["error"],
        "real_seconds": info["real_seconds"], "stdout": info["stdout"],
        "stderr": info["stderr"], "flight_id": info["flight_id"], "flight": None,
    }
    if info["status"] == "running":
        log = Path(info["log_path"])
        state = runner.read_live_log(log) if log.exists() else {"snapshot": None}
        snapshot = state.get("snapshot") or {}
        response["live"] = {
            "events": snapshot.get("events") or [],
            "segments": snapshot.get("segments") or [],
            "stats": snapshot.get("stats") or {},
            "now": snapshot.get("now") or 0.0,
            "warnings": snapshot.get("warnings") or [],
            "errors": snapshot.get("errors") or [],
            "samples_tail": (snapshot.get("samples") or [])[-400:],
        }
    elif info["flight_id"]:
        payload = storage.load(info["flight_id"])
        response["flight"] = payload
    # porządek w pamięci: nie trzymaj uruchomień starszych niż godzina
    for key, value in list(RUNS.items()):
        if time.time() - value["started"] > 3600 and value["status"] != "running":
            RUNS.pop(key, None)
    return response


# ---------------------------------------------------------------------- loty
@app.get("/api/flights")
def api_flights(limit: int = 20) -> List[Dict[str, Any]]:
    """Historia ostatnich lotów."""
    return storage.list_flights(limit=max(1, min(limit, 100)))


@app.get("/api/flights/{flight_id}")
def api_flight(flight_id: str) -> Dict[str, Any]:
    """Pełne dane lotu (format do odtwarzania i zapisu)."""
    payload = storage.load(flight_id)
    if payload is None:
        raise HTTPException(404, "Nie znaleziono lotu.")
    return payload


CSV_COLUMNS = ["t", "x", "y", "z", "yaw", "vx", "vy", "vz", "battery", "state"]


@app.get("/api/flights/{flight_id}/csv")
def api_flight_csv(flight_id: str) -> StreamingResponse:
    """Eksport telemetrii lotu do CSV."""
    payload = storage.load(flight_id)
    if payload is None:
        raise HTTPException(404, "Nie znaleziono lotu.")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for sample in payload.get("samples") or []:
        writer.writerow(sample)
    content = "\ufeff" + buffer.getvalue()  # BOM: poprawna polska czcionka w Excelu
    name = f"{payload.get('script_name', 'lot').rsplit('.', 1)[0]}-{flight_id}.csv"
    return StreamingResponse(
        iter([content]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/flights/{flight_id}/json")
def api_flight_json(flight_id: str) -> JSONResponse:
    """Pobranie lotu jako pliku JSON."""
    payload = storage.load(flight_id)
    if payload is None:
        raise HTTPException(404, "Nie znaleziono lotu.")
    name = f"{payload.get('script_name', 'lot').rsplit('.', 1)[0]}-{flight_id}.json"
    return JSONResponse(content=payload, headers={
        "Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/flights/import")
async def api_import_flight(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Importuj lot z pliku JSON (zapis w historii pod nowym identyfikatorem)."""
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, "Plik nie jest poprawnym JSON.")
    try:
        saved = storage.save_imported(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": saved["id"], "flight": saved}


@app.delete("/api/flights/{flight_id}")
def api_delete_flight(flight_id: str) -> Dict[str, Any]:
    """Usuń lot z historii."""
    if not storage.delete(flight_id):
        raise HTTPException(404, "Nie znaleziono lotu.")
    return {"deleted": flight_id}


@app.get("/api/health", response_class=PlainTextResponse)
def api_health() -> str:
    return "ok"
