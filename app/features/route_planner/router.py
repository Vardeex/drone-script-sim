"""Endpointy funkcji „Planer trasy” (montowane przez rdzeń pod ``/api/route_planner``).

* ``GET  /info``      - limity Tello/dronemoves, dostępność kontroli kolizji
* ``POST /validate``  - walidacja trasy (+ kolizje, gdy funkcja przeszkód włączona)
* ``POST /preview``   - zaplanowany tor, czas lotu i zużycie baterii
* ``POST /code``      - wygenerowany skrypt (tryb ``smooth`` albo ``simple``)
* ``POST /load``      - wczytanie trasy z bloku-znacznika w skrypcie
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import analyse, codegen_simple, codegen_smooth, validate
from .model import (
    HEADINGS, MAX_HEIGHT_CM, MAX_MOVE_CM, MAX_RADIUS_CM, MAX_SPEED_CMS,
    MIN_HEIGHT_CM, MIN_MOVE_CM, MIN_SPEED_CMS, Route, RouteError,
    load_route_from_script,
)

router = APIRouter()


class RouteRequest(BaseModel):
    """Trasa w formacie JSON planera (format ``dronesim-route``)."""

    route: Dict[str, Any] = Field(..., description="Trasa: points[], default_speed, ...")
    scene: Optional[Dict[str, Any]] = Field(
        None, description="Scena przeszkód do kontroli kolizji (opcjonalnie)")
    margin_cm: Optional[float] = Field(None, ge=0, le=200)


class CodeRequest(RouteRequest):
    """Żądanie wygenerowania kodu (tryb z trasy albo wymuszony)."""

    mode: Optional[str] = Field(None, description="smooth | simple (nadpisuje tryb trasy)")


class ScriptRequest(BaseModel):
    """Skrypt, z którego wczytujemy trasę (blok-znacznik)."""

    source: str = ""


def _parse(request: RouteRequest) -> Route:
    try:
        return Route.from_dict(request.route)
    except RouteError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/info")
def api_info() -> Dict[str, Any]:
    """Limity i możliwości planera (do podpowiedzi w UI)."""
    return {
        "id": "route_planner",
        "headings": list(HEADINGS),
        "modes": [{"id": "smooth", "label": "Płynna (dronemoves)"},
                  {"id": "simple", "label": "Prosta (djitellopy)"}],
        "limits": {
            "min_move_cm": MIN_MOVE_CM,
            "max_move_cm": MAX_MOVE_CM,
            "min_speed_cms": MIN_SPEED_CMS,
            "max_speed_cms": MAX_SPEED_CMS,
            "min_height_cm": MIN_HEIGHT_CM,
            "max_height_cm": MAX_HEIGHT_CM,
            "max_radius_cm": MAX_RADIUS_CM,
        },
        "collision_check": analyse.available(),
    }


@router.post("/validate")
def api_validate(request: RouteRequest) -> Dict[str, Any]:
    """Sprawdź trasę: limity, kolizje (jeśli przeszkody włączone), baterię."""
    route = _parse(request)
    return validate.validate(route, request.scene, request.margin_cm)


@router.post("/preview")
def api_preview(request: RouteRequest) -> Dict[str, Any]:
    """Zaplanowany tor (punkty z numerem i wysokością) + czas i bateria."""
    route = _parse(request)
    result = validate.preview(route)
    result["legs_cm"] = [round(v, 1) for v in route.leg_lengths()]
    return result


@router.post("/code")
def api_code(request: CodeRequest) -> Dict[str, Any]:
    """Wygeneruj skrypt dla trasy (tryb ``smooth`` = dronemoves, ``simple`` = djitellopy)."""
    route = _parse(request)
    mode = (request.mode or route.mode or "smooth").lower()
    if mode not in ("smooth", "simple"):
        raise HTTPException(400, "Tryb generowania musi być 'smooth' albo 'simple'.")
    route.mode = mode
    generator = codegen_smooth.generate if mode == "smooth" else codegen_simple.generate
    try:
        code = generator(route)
    except RouteError as exc:
        raise HTTPException(400, str(exc)) from exc
    report = validate.validate(route, request.scene, request.margin_cm)
    warnings: List[str] = [p["message"] for p in report["problems"]
                           if p["level"] == "warning"]
    return {"mode": mode, "code": code, "problems": report["problems"],
            "errors": report["errors"], "warnings": warnings,
            "stats": report["stats"]}


@router.post("/load")
def api_load(request: ScriptRequest) -> Dict[str, Any]:
    """Wczytaj trasę z bloku-znacznika w skrypcie (grzeczna odmowa dla innych)."""
    try:
        route = load_route_from_script(request.source)
    except RouteError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"route": route.as_dict()}
