"""Magazyn lotów - zapis/odczyt plików JSON w katalogu ``flights/``.

Każdy lot to osobny plik ``<id>.json`` z pełnymi danymi (telemetria, zdarzenia,
ostrzeżenia, kod skryptu). ``flights/index.json`` przechowuje skróconą
historię ostatnich lotów dla UI.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .sim.core import FlightData

_INDEX_NAME = "index.json"
_LOCK = threading.Lock()
MAX_INDEX = 50


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    """Identyfikator lotu: znacznik czasu + sufiks (sortowalny)."""
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def _safe_id(flight_id: str) -> str:
    """Walidacja identyfikatora (tylko bezpieczne znaki - ochrona przed ..)."""
    if not flight_id or len(flight_id) > 80 or not all(
            c.isalnum() or c in "-_" for c in flight_id):
        raise ValueError("Nieprawidłowy identyfikator lotu.")
    return flight_id


def flight_to_dict(flight: FlightData, flight_id: str, created_at: Optional[str] = None,
                   real_seconds: float = 0.0) -> Dict[str, Any]:
    """Pełny zapis lotu (format JSON wymienny między aplikacjami)."""
    return {
        "format": "drone-script-simulator",
        "version": 1,
        "id": flight_id,
        "created_at": created_at or _now(),
        "script_name": flight.script_name,
        "adapter": flight.adapter,
        "status": flight.status,
        "final_state": flight.final_state,
        "duration": round(flight.duration, 3),
        "real_seconds": real_seconds,
        "stats": flight.stats,
        "limits": flight.limits,
        "script_source": flight.script_source,
        "samples": flight.samples,
        "events": flight.events,
        "segments": flight.segments,
        "warnings": flight.warnings,
        "errors": flight.errors,
        "stdout": flight.stdout,
        "stderr": flight.stderr,
    }


def save(flight: FlightData, flight_id: Optional[str] = None,
         real_seconds: float = 0.0) -> Dict[str, Any]:
    """Zapisz lot i dopisz wpis do indeksu; zwróć zapisany słownik."""
    paths.ensure_dirs()
    flight_id = _safe_id(flight_id or new_id())
    payload = flight_to_dict(flight, flight_id, real_seconds=real_seconds)
    target = paths.FLIGHTS_DIR / f"{flight_id}.json"
    with _LOCK:
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _update_index(payload)
    return payload


def _index_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Skrócony wpis indeksu (to, co pokazuje historia lotów)."""
    stats = payload.get("stats") or {}
    return {
        "id": payload.get("id"),
        "created_at": payload.get("created_at"),
        "script_name": payload.get("script_name"),
        "adapter": payload.get("adapter"),
        "status": payload.get("status"),
        "duration": payload.get("duration"),
        "events": len(payload.get("events") or []),
        "warnings": len(payload.get("warnings") or []),
        "errors": len(payload.get("errors") or []),
        "distance_cm": stats.get("distance_cm"),
        "max_height_cm": stats.get("max_height_cm"),
        "battery_used_pct": stats.get("battery_used_pct"),
    }


def _read_index() -> List[Dict[str, Any]]:
    index_path = paths.FLIGHTS_DIR / _INDEX_NAME
    if not index_path.exists():
        return []
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _update_index(payload: Dict[str, Any]) -> None:
    entries = [e for e in _read_index() if e.get("id") != payload.get("id")]
    entries.insert(0, _index_entry(payload))
    index_path = paths.FLIGHTS_DIR / _INDEX_NAME
    index_path.write_text(json.dumps(entries[:MAX_INDEX], ensure_ascii=False, indent=1),
                          encoding="utf-8")


def load(flight_id: str) -> Optional[Dict[str, Any]]:
    """Wczytaj lot z pliku JSON (None, jeśli nie istnieje)."""
    try:
        safe = _safe_id(flight_id)
    except ValueError:
        return None
    target = paths.FLIGHTS_DIR / f"{safe}.json"
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_imported(payload: Dict[str, Any], flight_id: Optional[str] = None) -> Dict[str, Any]:
    """Importuj lot z pliku JSON wgranego przez użytkownika (zapis pod nowym id)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("Plik nie jest lotem Drone Script Simulator (brak 'samples').")
    paths.ensure_dirs()
    flight_id = _safe_id(flight_id or new_id())
    payload = dict(payload)
    payload["id"] = flight_id
    payload.setdefault("created_at", _now())
    payload.setdefault("format", "drone-script-simulator")
    payload.setdefault("events", [])
    payload.setdefault("warnings", [])
    payload.setdefault("errors", [])
    payload.setdefault("segments", [])
    payload.setdefault("stdout", [])
    payload.setdefault("stderr", [])
    payload.setdefault("stats", {})
    target = paths.FLIGHTS_DIR / f"{flight_id}.json"
    with _LOCK:
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _update_index(payload)
    return payload


def delete(flight_id: str) -> bool:
    """Usuń lot (plik + wpis indeksu). Zwraca False, jeśli nie istniał."""
    try:
        safe = _safe_id(flight_id)
    except ValueError:
        return False
    target = paths.FLIGHTS_DIR / f"{safe}.json"
    if not target.exists():
        return False
    with _LOCK:
        target.unlink()
        entries = [e for e in _read_index() if e.get("id") != safe]
        (paths.FLIGHTS_DIR / _INDEX_NAME).write_text(
            json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def list_flights(limit: int = 20) -> List[Dict[str, Any]]:
    """Historia ostatnich lotów (z indeksu; brak indeksu -> skan katalogu)."""
    paths.ensure_dirs()
    entries = _read_index()
    if not entries:
        for file in sorted(paths.FLIGHTS_DIR.glob("*.json")):
            if file.name == _INDEX_NAME:
                continue
            try:
                payload = json.loads(file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(payload, dict) and "samples" in payload:
                payload.setdefault("id", file.stem)
                entries.append(_index_entry(payload))
        entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return entries[:limit]
