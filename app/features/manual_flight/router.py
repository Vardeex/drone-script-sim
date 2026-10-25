"""Endpointy funkcji „Lot ręczny” (montowane przez rdzeń pod ``/api/manual_flight``).

* ``POST /start``      - nowa sesja (opcjonalnie scena do ostrzeżeń o kolizji)
* ``POST /takeoff``    - start (wzniesienie na 80 cm)
* ``POST /rc``         - odcinek RC (``lr, fb, ud, yaw, dt``) -> nowy stan
* ``POST /land``       - lądowanie
* ``POST /speed``      - prędkość manewrowa (10-100)
* ``POST /record``     - włącz/wyłącz nagrywanie
* ``GET  /state``      - bieżący stan (bez ruchu)
* ``GET  /recording``  - podsumowanie nagrania + punkty kontrolne/zatrzymań
* ``POST /script``     - wygeneruj skrypt (``variant``: ``rc`` albo ``simple``)
* ``POST /stop``       - zamknij sesję
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import codegen, session

router = APIRouter()


class StartRequest(BaseModel):
    """Nowa sesja lotu ręcznego."""

    speed: int = Field(50, description="Prędkość manewrowa 10-100")
    scene: Optional[Dict[str, Any]] = Field(
        None, description="Scena przeszkód (format JSON) do ostrzeżeń o kolizji")
    margin_cm: float = Field(session.DEFAULT_MARGIN_CM, description="Margines ostrzeżenia")


class RcRequest(BaseModel):
    """Odcinek sterowania RC (konwencja Tello: lr+ = prawo, yaw+ = w prawo)."""

    lr: int = 0
    fb: int = 0
    ud: int = 0
    yaw: int = 0
    dt: float = Field(session.MAX_DT_S, description="Czas odcinka [s] (limit 0.3)")


class SpeedRequest(BaseModel):
    speed: int = 50


class RecordRequest(BaseModel):
    enabled: bool = True


class ScriptRequest(BaseModel):
    variant: str = Field("rc", description="``rc`` (wierny) albo ``simple`` (move_*/rotate_*)")


def _require_session() -> "session.ManualSession":
    current = session.current()
    if current is None:
        raise HTTPException(404, "Lot ręczny nie jest uruchomiony - najpierw POST /start.")
    return current


@router.get("/variants")
def api_variants() -> Dict[str, Any]:
    """Warianty generowanego skryptu (etykiety do UI)."""
    return {"variants": [{"id": key, "label": label}
                         for key, (label, _fn) in codegen.VARIANTS.items()]}


@router.post("/start")
def api_start(request: StartRequest) -> Dict[str, Any]:
    """Utwórz nową sesję (poprzednia jest zastępowana)."""
    created = session.start_session(speed=request.speed, scene=request.scene,
                                    margin_cm=request.margin_cm)
    return created.state()


@router.post("/takeoff")
def api_takeoff() -> Dict[str, Any]:
    """Start drona (wzniesienie na 80 cm)."""
    return _require_session().start()


@router.post("/rc")
def api_rc(request: RcRequest) -> Dict[str, Any]:
    """Wykonaj odcinek RC i zwróć nowy stan."""
    return _require_session().rc(request.lr, request.fb, request.ud, request.yaw,
                                 request.dt)


@router.post("/land")
def api_land() -> Dict[str, Any]:
    """Lądowanie."""
    return _require_session().land()


@router.post("/speed")
def api_speed(request: SpeedRequest) -> Dict[str, Any]:
    """Ustaw prędkość manewrową."""
    return _require_session().set_speed(request.speed)


@router.post("/record")
def api_record(request: RecordRequest) -> Dict[str, Any]:
    """Włącz/wyłącz nagrywanie."""
    return _require_session().set_recording(request.enabled)


@router.get("/state")
def api_state() -> Dict[str, Any]:
    """Bieżący stan sesji (bez wykonywania ruchu)."""
    return _require_session().state()


@router.get("/recording")
def api_recording() -> Dict[str, Any]:
    """Podsumowanie nagrania: liczba odcinków, punkty kontrolne i zatrzymania."""
    current = _require_session()
    data = current.flight_data()
    return {
        "segments": len(current.recording),
        "duration": round(data.duration, 2),
        "control_points": [{"t": round(t, 2), "x": round(x, 1), "y": round(y, 1),
                            "z": round(z, 1)}
                           for t, x, y, z in current.control_points()],
        "stop_points": [{"t": round(t, 2), "x": round(x, 1), "y": round(y, 1),
                         "z": round(z, 1)}
                        for t, x, y, z in current.stop_points()],
        "warnings": list(current.warnings),
    }


@router.post("/script")
def api_script(request: ScriptRequest) -> Dict[str, Any]:
    """Wygeneruj skrypt Pythona z nagrania (do wklejenia w edytor)."""
    current = _require_session()
    if not current.recording:
        raise HTTPException(400, "Brak nagrania - włącz „Nagrywaj” i polataj chwilę.")
    try:
        source = codegen.generate(current.recording, variant=request.variant,
                                  speed=current.speed)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"variant": request.variant,
            "label": codegen.VARIANTS[request.variant][0],
            "segments": len(current.recording),
            "source": source}


@router.post("/stop")
def api_stop() -> Dict[str, Any]:
    """Zamknij sesję lotu ręcznego."""
    return {"closed": session.close_session()}
