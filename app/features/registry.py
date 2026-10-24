"""Rejestr wtyczek aplikacji (punkt rozszerzeń nr 1).

Wtyczka = katalog z plikiem ``plugin.json``. Rdzeń zna **dwa źródła**:

* ``app/features/<id>/`` - wtyczki wbudowane (``obstacles``, ``route_planner``),
* ``plugins/<id>/`` w katalogu projektu - wtyczki zewnętrzne (użytkownika).

Rdzeń skanuje oba, waliduje manifesty i montuje wtyczki **w kolejności
zależności** (``requires`` w manifeście). Wtyczka, która ma błędny manifest,
niespełnione zależności albo której kod rzuca wyjątek przy wczytaniu, jest
**wyłączana** - błąd trafia do logu i do UI (``GET /api/plugins``), a aplikacja
działa dalej.

Stan włącz/wyłącz trzymamy w ``config.json`` (sekcja ``features``), więc
zmiana działa po restarcie serwera.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config, paths
from . import plugin_model
from .plugin_model import ManifestError, read_manifest

#: katalog wtyczek wbudowanych
BUILTIN_DIR: Path = Path(__file__).resolve().parent

#: nazwa katalogu wtyczek zewnętrznych w katalogu projektu
EXTERNAL_DIR_NAME = "plugins"

#: nazwa pliku manifestu (zgodna wstecz z ``feature.json``)
MANIFEST_NAME = "plugin.json"
LEGACY_MANIFEST_NAME = "feature.json"

#: stany wtyczki pokazywane w UI
STATE_ENABLED = "enabled"
STATE_DISABLED = "disabled"
STATE_ERROR = "error"

#: alias pakietu dla wtyczek zewnętrznych (``app.plugins_ext.<id>``)
EXTERNAL_PACKAGE = "app.plugins_ext"


def _package_dir(plugin_dir: Path) -> Path:
    """Katalog z kodem Pythona wtyczki: ``<plugin>/src`` albo sam katalog wtyczki."""
    candidate = plugin_dir / "src"
    return candidate if (candidate / "__init__.py").is_file() else plugin_dir


def _static_dir(record: "PluginRecord") -> Optional[Path]:
    """Katalog plików statycznych wtyczki (``static`` z manifestu).

    * wtyczka **wbudowana**: ``static`` to ścieżka od katalogu ``app/``
      (``static/js/features/<id>``) - zgodnie z tym, jak traktował ją rdzeń 0.x,
    * wtyczka **zewnętrzna**: ``static`` to ścieżka wewnątrz katalogu wtyczki.

    Ścieżka z manifestu musi leżeć w dozwolonym katalogu - inaczej ``None``
    (ochrona przed ``../``).
    """
    static_rel = record.manifest.get("static") or ""
    if not static_rel:
        return None
    base = paths.APP_DIR if record.source == "builtin" else record.directory
    folder = (base / static_rel).resolve()
    try:
        folder.relative_to(base.resolve())
    except ValueError:
        return None
    return folder if folder.is_dir() else None


def _import_package(record: "PluginRecord") -> str:
    """Zaimportuj pakiet wtyczki i zwróć nazwę modułu ("" = wtyczka bez Pythona).

    Wtyczka wbudowana importuje się normalnie (``app.features.<id>``). Wtyczki
    zewnętrzne ładujemy z ``plugins/`` pod aliasem ``app.plugins_ext.<id>``,
    więc nie muszą być częścią pakietu aplikacji.
    """
    plugin_dir = record.directory
    package_dir = _package_dir(plugin_dir)
    if record.source == "external":
        module_name = f"{EXTERNAL_PACKAGE}.{record.id}"
        if EXTERNAL_PACKAGE not in sys.modules:
            namespace = importlib.util.module_from_spec(
                importlib.util.spec_from_loader(EXTERNAL_PACKAGE, loader=None))
            namespace.__path__ = []          # type: ignore[attr-defined]
            sys.modules[EXTERNAL_PACKAGE] = namespace
        init_file = package_dir / "__init__.py"
        if not init_file.is_file():
            return ""
        # czyścimy stary wpis: przy ponownym ładowaniu (restart testów) moduł
        # z poprzedniego procesu/ścieżki ma ``spec`` wskazujący na nieistniejące
        # pliki i ``importlib.reload`` kończy się „spec not found”.
        for name in [key for key in sys.modules
                     if key == module_name or key.startswith(f"{module_name}.")]:
            sys.modules.pop(name, None)
        sys.modules[EXTERNAL_PACKAGE].__path__ = [str(plugin_dir.parent)]  # type: ignore[attr-defined]
        spec = importlib.util.spec_from_file_location(
            module_name, init_file, submodule_search_locations=[str(package_dir)])
        if spec is None or spec.loader is None:
            raise ImportError(f"nie można załadować pakietu wtyczki {record.id}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module_name
    return f"{__package__}.{plugin_dir.name}"


@dataclass
class PluginRecord:
    """Wtyczka znaleziona przez rejestr: manifest, źródło i stan."""

    manifest: Dict[str, Any]
    source: str                       # "builtin" albo "external"
    directory: Path
    state: str = STATE_DISABLED
    error: str = ""
    package: str = ""
    static_url: str = ""
    installed: bool = False
    hooks: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def enabled(self) -> bool:
        return self.state == STATE_ENABLED


# --------------------------------------------------------------------- odkrywanie
def external_dir(root: Optional[Path] = None) -> Path:
    """Katalog wtyczek zewnętrznych (``<projekt>/plugins`` albo podany)."""
    return Path(root) if root is not None else paths.PROJECT_ROOT / EXTERNAL_DIR_NAME


def _plugin_dirs(root: Path) -> List[Path]:
    """Podkatalogi z manifestem wtyczki (kolejność alfabetyczna)."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith((".", "_")))


def discover(builtin_root: Optional[Path] = None,
             external_root: Optional[Path] = None) -> List[PluginRecord]:
    """Znajdź wszystkie wtyczki (bez decydowania, czy są włączone).

    Katalog bez manifestu jest pomijany (to nie jest wtyczka). Błąd manifestu
    daje rekord w stanie ``error`` - widoczny w UI, nie psujący aplikacji.
    """
    records: List[PluginRecord] = []
    seen: Dict[str, PluginRecord] = {}
    roots = [("builtin", Path(builtin_root) if builtin_root is not None else BUILTIN_DIR),
             ("external", external_dir(external_root) if external_root is not None
              else external_dir())]
    for source, root in roots:
        for directory in _plugin_dirs(root):
            manifest_file = directory / MANIFEST_NAME
            legacy_file = directory / LEGACY_MANIFEST_NAME
            if not manifest_file.is_file() and not legacy_file.is_file():
                if source == "external":
                    print(f"[plugins] pomijam '{directory.name}': brak {MANIFEST_NAME}",
                          file=sys.stderr)
                continue
            try:
                if manifest_file.is_file():
                    manifest = read_manifest(directory)
                else:
                    manifest = _read_legacy_manifest(directory)
            except ManifestError as exc:
                record = PluginRecord(manifest={"id": directory.name,
                                                "name": directory.name},
                                      source=source, directory=directory,
                                      state=STATE_ERROR, error=str(exc))
                print(f"[plugins] błąd manifestu '{directory.name}': {exc}",
                      file=sys.stderr)
                records.append(record)
                continue
            if manifest["id"] != directory.name and source == "builtin":
                print(f"[plugins] uwaga: katalog '{directory.name}' ma id "
                      f"'{manifest['id']}'", file=sys.stderr)
            if manifest["id"] in seen:
                print(f"[plugins] pomijam '{directory.name}': id '{manifest['id']}' "
                      f"już zajęte przez {seen[manifest['id']].source}",
                      file=sys.stderr)
                continue
            record = PluginRecord(manifest=manifest, source=source, directory=directory)
            seen[manifest["id"]] = record
            records.append(record)
    return records


def _read_legacy_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """Wsteczna zgodność: starszy manifest ``feature.json`` -> model wtyczki."""
    import json

    from .plugin_model import validate_manifest

    raw = json.loads((plugin_dir / LEGACY_MANIFEST_NAME).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestError(f"{LEGACY_MANIFEST_NAME} musi być obiektem JSON")
    converted = {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "version": str(raw.get("version") or "0.0.0"),
        "description": raw.get("description") or "",
        "author": raw.get("author") or "",
        "api_prefix": raw.get("api_prefix"),
        "static": raw.get("static"),
        "ui": raw.get("ui") or {},
        "requires": raw.get("requires") or [],
        "extension_points": raw.get("extension_points") or [],
        "requires_app": raw.get("requires_app") or "",
    }
    return validate_manifest(converted)


# ------------------------------------------------------------------- zależności
def sort_by_dependencies(records: List[PluginRecord]) -> List[PluginRecord]:
    """Posortuj wtyczki tak, by zależności były przed zależnymi.

    Kolejność wejściowa (alfabetyczna) jest punktem wyjścia, więc wynik jest
    deterministyczny. Wtyczka, która wymaga nieistniejącej wtyczki, oraz
    wtyczki w cyklu dostają stan ``error`` (nie przerywają sortowania).
    """
    by_id = {record.id: record for record in records}
    ordered: List[PluginRecord] = []
    pending = list(records)
    blocked: Dict[str, str] = {}
    for record in records:
        missing = [d for d in record.manifest.get("requires", []) if d not in by_id]
        if missing:
            blocked[record.id] = (f"wymaga nieistniejących wtyczek: "
                                  f"{', '.join(missing)}")
    while pending:
        progressed = False
        for record in list(pending):
            if record.id in blocked:
                continue
            deps = record.manifest.get("requires", [])
            if all(dep in {item.id for item in ordered} for dep in deps):
                ordered.append(record)
                pending.remove(record)
                progressed = True
        if not progressed:
            cycle = ", ".join(r.id for r in pending if r.id not in blocked)
            if cycle:
                for record in pending:
                    if record.id not in blocked:
                        blocked[record.id] = f"cykl zależności: {cycle}"
            break
    for record in records:
        if record.id in blocked:
            record.state = STATE_ERROR
            record.error = blocked[record.id]
            print(f"[plugins] wyłączam '{record.id}': {blocked[record.id]}",
                  file=sys.stderr)
    return ordered


# ---------------------------------------------------------------- włącz / wyłącz
def is_enabled(manifest: Dict[str, Any],
               settings: Optional[Dict[str, Any]] = None) -> bool:
    """Czy wtyczka jest włączona: manifest + nadpisanie z ``config.json``.

    Pole ``enabled`` w ``config.json`` (sekcja ``features``) ma pierwszeństwo
    przed manifestem - pozwala wyłączyć wtyczkę bez ruszania jej plików.
    """
    settings = config.features() if settings is None else settings
    override = settings.get(manifest["id"])
    if isinstance(override, dict) and "enabled" in override:
        return bool(override["enabled"])
    if isinstance(override, bool):
        return override
    return bool(manifest.get("enabled", True))


def set_enabled(plugin_id: str, enabled: bool) -> None:
    """Zapisz stan wtyczki w ``config.json`` (działa po restarcie serwera)."""
    config.set_feature_enabled(plugin_id, enabled)


def app_version() -> str:
    """Wersja aplikacji (``requires_app`` w manifestach porównujemy z nią)."""
    from .. import __version__ as version

    return version


# ------------------------------------------------------------------- montowanie
def load_router(record: PluginRecord) -> Any:
    """Zaimportuj ``router`` wtyczki (APIRouter FastAPI)."""
    module = importlib.import_module(f"{record.package}.router")
    return module.router


def register_hooks(record: PluginRecord, storage: Any) -> List[str]:
    """Wywołaj ``hooks.register(storage)`` wtyczki; zwróć nazwy hooków."""
    try:
        hooks = importlib.import_module(f"{record.package}.hooks")
    except ModuleNotFoundError:
        return []
    register = getattr(hooks, "register", None)
    if not callable(register):
        return []
    register(storage)
    return ["on_flight_saved"]


def prepare(record: PluginRecord) -> None:
    """Ustal stan, pakiet i adres statyków wtyczki (bez importu kodu)."""
    if record.state == STATE_ERROR:
        return
    manifest = record.manifest
    if not is_enabled(manifest):
        record.state = STATE_DISABLED
        return
    try:
        if not plugin_model.version_satisfies(app_version(), manifest.get("requires_app")):
            raise ManifestError(
                f"wymaga aplikacji {manifest.get('requires_app')}, "
                f"a jest {app_version()}")
    except ManifestError as exc:
        record.state = STATE_ERROR
        record.error = str(exc)
        print(f"[plugins] wyłączam '{record.id}': {exc}", file=sys.stderr)
        return
    record.state = STATE_ENABLED


def install(record: PluginRecord, app: Any, storage: Any,
            static_mount: str = "/static/features") -> None:
    """Zamontuj wtyczkę w aplikacji: statyki, router, hooki.

    Wyjątek (błąd składni, brak modułu, wyjątek w imporcie) **nie przerywa**
    startu aplikacji - wtyczka trafia do stanu ``error`` z komunikatem.
    """
    if record.state != STATE_ENABLED:
        return
    try:
        record.package = _import_package(record)
        statics = _static_dir(record)
        if statics is not None:
            from fastapi.staticfiles import StaticFiles

            record.static_url = f"{static_mount}/{record.id}"
            app.mount(record.static_url, StaticFiles(directory=str(statics)),
                      name=f"plugin-{record.id}")
        if record.package and (record.directory / "src").is_dir():
            router_module = record.directory / "src" / "router.py"
        else:
            router_module = record.directory / "router.py"
        if router_module.is_file():
            app.include_router(load_router(record),
                               prefix=record.manifest.get("api_prefix")
                               or f"/api/{record.id}")
        if record.package:
            record.hooks = register_hooks(record, storage)
        record.installed = True
    except Exception as exc:  # noqa: BLE001 - wtyczka nie może wywrócić aplikacji
        record.state = STATE_ERROR
        record.error = f"{type(exc).__name__}: {exc}"
        record.installed = False
        print(f"[plugins] nie udało się włączyć '{record.id}': {record.error}",
              file=sys.stderr)


def resolve_state(plugin_id: str, builtin_root: Optional[Path] = None,
                  external_root: Optional[Path] = None) -> str:
    """Stan wtyczki bez montowania: ``enabled`` / ``disabled`` / ``error``.

    Używane przez wtyczki, które chcą wiedzieć, czy ich zależność działa
    (np. planer sprawdza ``obstacles``). Nieznana wtyczka = ``disabled``.
    """
    for record in discover(builtin_root, external_root):
        if record.id != plugin_id:
            continue
        prepare(record)
        return record.state
    return STATE_DISABLED


def load_all(app: Any, storage: Any, builtin_root: Optional[Path] = None,
             external_root: Optional[Path] = None,
             static_mount: str = "/static/features") -> List[PluginRecord]:
    """Odkryj, posortuj, przygotuj i zamontuj wszystkie wtyczki.

    Zwraca **wszystkie** znalezione rekordy (także wyłączone i z błędem) -
    ``GET /api/plugins`` pokazuje je w UI.
    """
    records = discover(builtin_root, external_root)
    ordered = sort_by_dependencies(records)
    for record in ordered:
        prepare(record)
    for record in ordered:
        install(record, app, storage, static_mount)
    return records


# ------------------------------------------------- kompatybilność wstecz (0.x)
def enabled_features(settings: Optional[Dict[str, Any]] = None,
                     builtin_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Manifesty włączonych wtyczek (stary kontrakt ``registry``)."""
    settings = config.features() if settings is None else settings
    result: List[Dict[str, Any]] = []
    for record in sort_by_dependencies(discover(builtin_root=builtin_root)):
        if record.state == STATE_ERROR or not is_enabled(record.manifest, settings):
            continue
        manifest = dict(record.manifest)
        manifest["dir"] = record.directory.name
        manifest["source"] = record.source
        result.append(manifest)
    return result


def public_descriptor(record: PluginRecord) -> Dict[str, Any]:
    """Opis wtyczki dla UI (``GET /api/features`` i ``GET /api/plugins``)."""
    manifest = record.manifest
    return {
        "id": record.id,
        "name": manifest.get("name") or record.id,
        "description": manifest.get("description") or "",
        "version": manifest.get("version") or "",
        "author": manifest.get("author") or "",
        "requires": manifest.get("requires") or [],
        "requires_app": manifest.get("requires_app") or "",
        "extension_points": manifest.get("extension_points") or [],
        "source": record.source,
        "state": record.state,
        "error": record.error,
        "installed": record.installed,
        "api_prefix": manifest.get("api_prefix") or "",
        "static_url": record.static_url,
        "hooks": record.hooks,
        "ui": manifest.get("ui") or {},
    }
