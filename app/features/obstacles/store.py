"""Zapis i odczyt scen przeszkód.

Miejsca przechowywania:

* ``scenes/*.json`` - przykładowe scenie z repozytorium (tylko odczyt w UI),
* ``scenes/user/*.json`` - sceny użytkownika (katalog w ``.gitignore``).

Nazwa sceny to nazwa pliku bez rozszerzenia; dozwolone są litery, cyfry,
``-``, ``_`` i ``.`` (bez ścieżek - ochrona przed ``..``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ... import paths
from .model import Scene, SceneError

SCENES_DIR: Path = paths.PROJECT_ROOT / "scenes"
USER_DIR_NAME = "user"
MAX_SCENE_BYTES = 512 * 1024
MAX_OBSTACLES = 500
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\- ]{0,79}$")


def scenes_root() -> Path:
    """Katalog ze scenami przykładowymi (nadpisywalny w testach)."""
    return SCENES_DIR


def user_dir() -> Path:
    """Katalog własnych scen użytkownika (w katalogu danych, nie w programie)."""
    return paths.SCENES_USER_DIR


def ensure_dirs() -> None:
    """Utwórz katalog scen użytkownika."""
    user_dir().mkdir(parents=True, exist_ok=True)


def valid_name(name: str) -> str:
    """Sprawdź nazwę pliku sceny (ValueError z komunikatem po polsku)."""
    name = (name or "").strip()
    if name.lower().endswith(".json"):
        name = name[:-5]
    if not name or not _NAME_RE.match(name) or ".." in name:
        raise SceneError("Nieprawidłowa nazwa sceny (dozwolone litery, cyfry, myślnik, "
                         "podkreślenie, spacja; maks. 80 znaków).")
    return name


def _path_for(name: str, user: bool) -> Path:
    folder = user_dir() if user else scenes_root()
    return folder / f"{valid_name(name)}.json"


def _read_file(path: Path) -> Scene:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SceneError(f"Nie można przeczytać sceny: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SceneError(f"Scena '{path.name}' nie jest poprawnym JSON: {exc.msg}.") from exc
    return Scene.from_dict(data)


def list_scenes() -> List[Dict[str, Any]]:
    """Lista scen: przykładowe + użytkownika (z podglądem liczby przeszkód)."""
    items: List[Dict[str, Any]] = []
    for folder, user in ((scenes_root(), False), (user_dir(), True)):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            entry: Dict[str, Any] = {"name": path.stem, "user": user}
            try:
                scene = _read_file(path)
                entry["display_name"] = scene.name
                entry["description"] = scene.description
                entry["obstacles"] = len(scene.obstacles)
                entry["gates"] = len(scene.gates())
            except SceneError:
                entry["display_name"] = path.stem
                entry["description"] = "scena uszkodzona"
                entry["obstacles"] = 0
                entry["gates"] = 0
                entry["broken"] = True
            items.append(entry)
    return items


def load_scene(name: str) -> Scene:
    """Wczytaj scenę (najpierw użytkownika, potem przykładowe)."""
    user_path = _path_for(name, user=True)
    if user_path.exists():
        return _read_file(user_path)
    example_path = _path_for(name, user=False)
    if example_path.exists():
        return _read_file(example_path)
    raise SceneError(f"Nie znaleziono sceny '{name}'.")


def scene_exists(name: str) -> bool:
    try:
        return _path_for(name, True).exists() or _path_for(name, False).exists()
    except SceneError:
        return False


def save_scene(scene: Scene, name: Optional[str] = None,
               overwrite: bool = True) -> Dict[str, Any]:
    """Zapisz scenę użytkownika (zwraca opis jak w ``list_scenes``)."""
    scene_name = valid_name(name or scene.name)
    if len(scene.obstacles) > MAX_OBSTACLES:
        raise SceneError(f"Scena może mieć maksymalnie {MAX_OBSTACLES} przeszkód.")
    target = _path_for(scene_name, user=True)
    if not overwrite and (target.exists() or _path_for(scene_name, False).exists()):
        raise SceneError(f"Scena '{scene_name}' już istnieje - wybierz inną nazwę.")
    ensure_dirs()
    payload = scene.as_dict()
    payload["name"] = scene.name or scene_name
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if len(text.encode("utf-8")) > MAX_SCENE_BYTES:
        raise SceneError("Scena jest za duża (limit 512 KB).")
    target.write_text(text, encoding="utf-8")
    return {"name": scene_name, "user": True, "display_name": payload["name"],
            "description": scene.description, "obstacles": len(scene.obstacles),
            "gates": len(scene.gates())}


def delete_scene(name: str) -> bool:
    """Usuń scenę użytkownika (przykładowych nie da się usunąć)."""
    target = _path_for(name, user=True)
    if not target.exists():
        return False
    target.unlink()
    return True
