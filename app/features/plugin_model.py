"""Model i walidacja manifestu wtyczki (``plugin.json``).

Manifest jest jedynym kontraktem między rdzeniem a wtyczką. Rdzeń czyta go
przy starcie, sprawdza pola i **nie importuje** kodu wtyczki, dopóki manifest
jest poprawny i wszystkie zależności są spełnione.

Przykład (pełny opis pól w ``docs/plugins.md``)::

    {
      "id": "example_hello",
      "name": "Przykładowa wtyczka",
      "version": "1.0.0",
      "description": "Panel z tekstem i endpoint /api/example_hello/hello",
      "author": "Vardeex",
      "requires_app": ">=0.3.0",
      "requires": [],
      "extension_points": ["api", "ui.panel"]
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

#: nazwa pliku manifestu w katalogu wtyczki
MANIFEST_NAME = "plugin.json"

#: identyfikator: małe litery, cyfry, podkreślenia (katalog musi tak się nazywać)
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

#: pola wymagane w manifeście
REQUIRED_FIELDS = ("id", "name", "version", "description")

#: znane punkty rozszerzeń (wtyczka deklaruje, z których korzysta)
EXTENSION_POINTS = {
    "api": "Własne endpointy REST pod ``api_prefix`` (moduł ``router.py``)",
    "ui.panel": "Panel w zakładce (moduł z ``registerPanel``)",
    "ui.styles": "Arkusz CSS doładowywany przy starcie",
    "ui.scene_layer": "Warstwa 3D (moduł z ``createLayer``)",
    "flight.analyse": "Analiza lotu po symulacji (``hooks.on_flight_saved``)",
    "run.options": "Własne opcje uruchomienia (``getRunOptions`` w panelu)",
}


class ManifestError(ValueError):
    """Niepoprawny manifest wtyczki (komunikat trafia do logu i UI)."""


def _version_tuple(text: str) -> tuple:
    """``"1.2.3"`` -> ``(1, 2, 3)``; części niebędące liczbami traktujemy jako 0."""
    parts: List[int] = []
    for piece in str(text).strip().split("."):
        match = re.match(r"(\d+)", piece)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def version_satisfies(version: str, constraint: Optional[str]) -> bool:
    """Czy ``version`` spełnia ``constraint`` (``">=1.0.0"``, ``"==1.2.0"``, ``""``).

    Obsługujemy proste porównania (``>=``, ``>``, ``<=``, ``<``, ``==``, ``!=``),
    łączone przecinkiem jako koniunkcja - wystarcza do „minimalnej wersji
    aplikacji”.
    """
    if not constraint:
        return True
    for piece in str(constraint).split(","):
        piece = piece.strip()
        if not piece:
            continue
        match = re.match(r"^(>=|<=|==|!=|>|<)\s*(.+)$", piece)
        if not match:
            raise ManifestError(f"nieznany warunek wersji: {piece!r}")
        operator, wanted = match.group(1), _version_tuple(match.group(2))
        current = _version_tuple(version)
        checks = {
            ">=": current >= wanted, ">": current > wanted,
            "<=": current <= wanted, "<": current < wanted,
            "==": current == wanted, "!=": current != wanted,
        }
        if not checks[operator]:
            return False
    return True


def read_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """Wczytaj i zwaliduj ``plugin.json`` z katalogu wtyczki.

    :raises ManifestError: gdy plik nie istnieje, nie jest JSON-em albo brakuje
        wymaganych pól / pola mają zły typ
    """
    path = Path(plugin_dir) / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"brak pliku {MANIFEST_NAME}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"nie można odczytać {MANIFEST_NAME}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{MANIFEST_NAME} nie jest poprawnym JSON-em: "
                            f"linia {exc.lineno}, kolumna {exc.colno}") from exc
    return validate_manifest(raw)


def validate_manifest(raw: Any) -> Dict[str, Any]:
    """Sprawdź strukturę manifestu; zwróć go z uzupełnionymi domyślnymi polami."""
    if not isinstance(raw, dict):
        raise ManifestError("manifest musi być obiektem JSON")
    for field in REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"pole '{field}' jest wymagane i musi być tekstem")
    plugin_id = raw["id"].strip()
    if not ID_PATTERN.match(plugin_id):
        raise ManifestError(
            f"id '{plugin_id}' niepoprawne: małe litery, cyfry i '_', 2-48 znaków, "
            "pierwsza litera")
    requires = raw.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(i, str) for i in requires):
        raise ManifestError("pole 'requires' musi być listą identyfikatorów")
    if plugin_id in [item.strip() for item in requires]:
        raise ManifestError(f"wtyczka '{plugin_id}' nie może wymagać sama siebie")
    points = raw.get("extension_points") or []
    if not isinstance(points, list) or not all(isinstance(p, str) for p in points):
        raise ManifestError("pole 'extension_points' musi być listą tekstów")
    unknown = [p for p in points if p not in EXTENSION_POINTS]
    if unknown:
        raise ManifestError(
            f"nieznane punkty rozszerzeń: {', '.join(unknown)} "
            f"(dozwolone: {', '.join(sorted(EXTENSION_POINTS))})")
    ui = raw.get("ui") or {}
    if not isinstance(ui, dict):
        raise ManifestError("pole 'ui' musi być obiektem")
    styles = ui.get("styles") or []
    if not isinstance(styles, list) or not all(isinstance(s, str) for s in styles):
        raise ManifestError("pole 'ui.styles' musi być listą ścieżek")

    manifest: Dict[str, Any] = dict(raw)
    manifest.update({
        "id": plugin_id,
        "name": raw["name"].strip(),
        "version": str(raw["version"]).strip(),
        "description": raw["description"].strip(),
        "author": str(raw.get("author") or "").strip(),
        "requires_app": str(raw.get("requires_app") or "").strip(),
        "requires": [str(item).strip() for item in requires],
        "extension_points": list(points),
        "ui": {**ui, "styles": [str(item) for item in styles]},
        "api_prefix": str(raw.get("api_prefix") or f"/api/{plugin_id}"),
        "static": str(raw.get("static") or ""),
    })
    return manifest
