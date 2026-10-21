"""Rejestr opcjonalnych funkcji aplikacji (punkt rozszerzeń nr 1).

Funkcja = podkatalog ``app/features/<nazwa>/`` z plikiem ``feature.json``:

.. code-block:: json

    {
      "id": "obstacles",
      "name": "Przeszkody 3D",
      "enabled": true,
      "description": "Edytor przeszkód, kolizje, analiza lotu"
    }

Rdzeń nie zna nazw funkcji: skanuje katalog ``features``, czyta manifesty,
sprawdza ustawienia konfiguracji i montuje APIRouter funkcji pod prefiksem
``/api/<id>``. Wyłączenie funkcji (``"enabled": false`` w manifeście albo w
``config.json``) powoduje, że jej router nie istnieje, a pliki statyczne
funkcji nie są serwowane - aplikacja działa dalej bez niej.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

FEATURES_DIR: Path = Path(__file__).resolve().parent
MANIFEST_NAME = "feature.json"


def _feature_dirs(root: Optional[Path] = None) -> List[Path]:
    """Podkatalogi ``features`` zawierające manifest (kolejność alfabetyczna)."""
    base = Path(root) if root is not None else FEATURES_DIR
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / MANIFEST_NAME).exists())


def read_manifest(feature_dir: Path) -> Optional[Dict[str, Any]]:
    """Wczytaj manifest funkcji (None, gdy plik jest uszkodzony)."""
    try:
        data = json.loads((feature_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    data.setdefault("name", data["id"])
    data.setdefault("description", "")
    data.setdefault("enabled", True)
    return data


def is_enabled(manifest: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> bool:
    """Czy funkcja jest włączona: manifest + nadpisanie z konfiguracji.

    Pole ``enabled`` w ``config.json`` (sekcja ``features``) ma pierwszeństwo
    przed manifestem - pozwala wyłączyć funkcję bez ruszania jej plików.
    """
    settings = config.features() if settings is None else settings
    override = settings.get(manifest["id"])
    if isinstance(override, dict) and "enabled" in override:
        return bool(override["enabled"])
    if isinstance(override, bool):
        return override
    return bool(manifest.get("enabled", True))


def enabled_features(settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Manifesty wszystkich włączonych funkcji (z nazwą katalogu)."""
    settings = config.features() if settings is None else settings
    result = []
    for feature_dir in _feature_dirs():
        manifest = read_manifest(feature_dir)
        if manifest is None or not is_enabled(manifest, settings):
            continue
        manifest = dict(manifest)
        manifest["dir"] = feature_dir.name
        manifest["package"] = f"{__package__}.{feature_dir.name}"
        result.append(manifest)
    return result


def load_router(manifest: Dict[str, Any]) -> Any:
    """Zaimportuj i zwróć ``router`` z modułu funkcji (APIRouter FastAPI)."""
    module = importlib.import_module(f"{manifest['package']}.router")
    return module.router


def public_descriptor(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Opis funkcji dla frontendu (``GET /api/features``)."""
    return {
        "id": manifest["id"],
        "name": manifest.get("name") or manifest["id"],
        "description": manifest.get("description") or "",
        "ui": manifest.get("ui") or {},
    }
