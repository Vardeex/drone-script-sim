"""Endpointy funkcji „Przeszkody 3D” (montowane przez rdzeń pod ``/api/obstacles``).

* ``GET  /scenes``              - lista scen (przykładowe + użytkownika)
* ``GET  /scenes/{name}``       - treść sceny
* ``POST /scenes/{name}``       - zapis sceny użytkownika
* ``DELETE /scenes/{name}``     - usunięcie sceny użytkownika
* ``POST /scene/empty``         - nowa pusta scena
* ``POST /analyse``             - analiza dowolnej telemetrii względem sceny
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import collisions, store
from .model import KIND_LABELS, KINDS, Obstacle, Scene, SceneError

router = APIRouter()


class SceneSaveRequest(BaseModel):
    """Scena do zapisania (format JSON sceny)."""

    scene: Dict[str, Any] = Field(..., description="Scena: name, description, obstacles[]")
    overwrite: bool = Field(True, description="Nadpisz istniejącą scenę użytkownika")


class AnalyseRequest(BaseModel):
    """Analiza dowolnej telemetrii (np. w podglądzie bez zapisu lotu)."""

    scene: Dict[str, Any]
    samples: List[Dict[str, Any]] = Field(default_factory=list)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    margin_cm: float = Field(collisions.DEFAULT_MARGIN, ge=0, le=200)


@router.get("/info")
def api_info() -> Dict[str, Any]:
    """Parametry funkcji: typy przeszkód, rozmiar drona, domyślny margines."""
    return {
        "id": "obstacles",
        "kinds": [{"id": kind, "label": KIND_LABELS[kind]} for kind in KINDS],
        "drone_size_cm": [collisions.DRONE_WIDTH, collisions.DRONE_LENGTH,
                          collisions.DRONE_HEIGHT],
        "default_margin_cm": collisions.DEFAULT_MARGIN,
        "max_margin_cm": 200,
        "max_obstacles": store.MAX_OBSTACLES,
    }


@router.get("/scenes")
def api_scenes() -> List[Dict[str, Any]]:
    """Lista scen (przykładowe z repozytorium + sceny użytkownika)."""
    return store.list_scenes()


@router.get("/scenes/{name}")
def api_scene(name: str) -> Dict[str, Any]:
    """Treść sceny (format JSON)."""
    try:
        scene = store.load_scene(name)
    except SceneError as exc:
        raise HTTPException(404, str(exc)) from exc
    data = scene.as_dict()
    data["file"] = store.valid_name(name)
    return data


@router.post("/scenes/{name}")
def api_scene_save(name: str, request: SceneSaveRequest) -> Dict[str, Any]:
    """Zapisz scenę w ``scenes/user`` (tylko sceny użytkownika)."""
    try:
        scene = Scene.from_dict(request.scene)
        saved = store.save_scene(scene, name=name, overwrite=request.overwrite)
    except SceneError as exc:
        raise HTTPException(400, str(exc)) from exc
    saved["scene"] = store.load_scene(saved["name"]).as_dict()
    return saved


@router.delete("/scenes/{name}")
def api_scene_delete(name: str) -> Dict[str, Any]:
    """Usuń scenę użytkownika."""
    try:
        if not store.delete_scene(name):
            raise HTTPException(404, f"Nie znaleziono sceny '{name}'.")
    except SceneError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": name}


@router.post("/scene/empty")
def api_empty_scene() -> Dict[str, Any]:
    """Nowa pusta scena (dimension: pomieszczenie 4 x 4 x 2,5 m, bez przeszkód)."""
    return Scene(name="Nowa scena", room=(400.0, 400.0, 250.0), obstacles=[]).as_dict()


@router.post("/validate")
def api_validate(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sprawdź poprawność sceny bez zapisu (edytor używa przy imporcie)."""
    try:
        scene = Scene.from_dict(data)
    except SceneError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"scene": scene.as_dict(), "obstacles": len(scene.obstacles),
            "gates": len(scene.gates())}


@router.post("/analyse")
def api_analyse(request: AnalyseRequest) -> Dict[str, Any]:
    """Analiza telemetrii względem sceny (kolizje, zbliżenia, bramki)."""
    try:
        scene = Scene.from_dict(request.scene)
    except SceneError as exc:
        raise HTTPException(400, str(exc)) from exc
    return collisions.analyse_flight(request.samples, request.events,
                                     scene.as_dict(), margin=request.margin_cm)


@router.get("/presets/{kind}")
def api_preset(kind: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
               yaw_deg: float = 0.0) -> Dict[str, Any]:
    """Domyślne wymiary nowej przeszkody danego typu (szybkie dodawanie w UI)."""
    presets: Dict[str, Dict[str, Any]] = {
        "box": {"size": [20, 200, 200], "name": "ściana"},
        "cylinder": {"size": [30, 30, 150], "name": "słup"},
        "gate": {"size": [100, 5, 100], "opening": [60, 60], "thickness": 5, "name": "bramka"},
        "plane": {"size": [400, 400, 5], "thickness": 5, "name": "sufit"},
    }
    if kind not in presets:
        raise HTTPException(404, f"Nieznany typ przeszkody: {kind}")
    preset: Optional[Dict[str, Any]] = presets[kind]
    obstacle = Obstacle(kind=kind, position=(x, y, z), yaw_deg=yaw_deg, **preset)
    return obstacle.as_dict()
