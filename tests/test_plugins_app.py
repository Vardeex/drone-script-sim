"""Testy integracyjne systemu wtyczek: montowanie w aplikacji, przełączanie,
przykładowa wtyczka, wtyczka z błędem i aplikacja bez żadnej wtyczki.

Każdy test buduje **własną** aplikację (``FastAPI``) albo przeładowuje
``app.server`` z tymczasowym ``config.json``, więc nie zależy od stanu
``config.json`` w repozytorium ani od działającego serwera.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import storage
from app.features import registry
from tests.test_plugins_registry import write_plugin


def build_app(external_root: Path, builtin_root: Path | None = None) -> FastAPI:
    """Nowa aplikacja z wtyczkami z podanych katalogów (bez rdzenia server.py)."""
    app = FastAPI()
    registry.load_all(app, storage, builtin_root=builtin_root, external_root=external_root)
    return app


def test_example_plugin_loads_and_serves_api_and_static():
    """Przykładowa wtyczka ``plugins/example_hello``: endpoint + statyki."""
    plugins_root = registry.external_dir()
    records = registry.discover(builtin_root=plugins_root / "brak",
                                external_root=plugins_root)
    ids = [r.id for r in records]
    assert "example_hello" in ids, ids
    app = build_app(plugins_root, builtin_root=plugins_root / "brak")
    with TestClient(app) as client:
        answer = client.get("/api/example_hello/hello", params={"name": "Marku"})
        assert answer.status_code == 200
        assert "Marku" in answer.json()["message"]
        assert answer.json()["plugin"] == "example_hello"
        assert client.get("/api/example_hello/info").json()["id"] == "example_hello"
        assert client.get("/static/features/example_hello/panel.js").status_code == 200
        assert client.get("/static/features/example_hello/panel.css").status_code == 200


def test_plugin_with_broken_code_does_not_break_app(tmp_path):
    """Wtyczka z błędem składni: stan ``error``, reszta aplikacji działa."""
    folder = write_plugin(tmp_path, "zepsuta", api_prefix="/api/zepsuta")
    (folder / "src" / "__init__.py").write_text("", encoding="utf-8")
    (folder / "src" / "router.py").write_text("def zle(:", encoding="utf-8")
    good = write_plugin(tmp_path, "dobra", api_prefix="/api/dobra")
    (good / "src" / "__init__.py").write_text("", encoding="utf-8")
    (good / "src" / "router.py").write_text(
        "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"
        "@router.get('/x')\ndef x() -> dict:\n    return {'ok': True}\n",
        encoding="utf-8")

    app = build_app(tmp_path, builtin_root=tmp_path / "brak")
    with TestClient(app) as client:
        assert client.get("/api/dobra/x").json() == {"ok": True}
        assert client.get("/api/zepsuta/cokolwiek").status_code == 404
    records = {r.id: r for r in registry.discover(
        builtin_root=tmp_path / "brak", external_root=tmp_path)}
    assert records["dobra"].state != registry.STATE_ERROR


def test_app_works_with_all_plugins_disabled(monkeypatch, tmp_path):
    """Aplikacja działa, gdy wszystkie wtyczki są wyłączone w ``config.json``."""
    payload = {"features": {"obstacles": {"enabled": False},
                            "route_planner": {"enabled": False},
                            "manual_flight": {"enabled": False},
                            "example_hello": {"enabled": False}}}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DRONESIM_CONFIG_FILE", str(cfg))
    import app.server as server

    module = importlib.reload(server)
    try:
        assert not [r for r in module.PLUGINS if r.enabled]
        with TestClient(module.app) as client:
            assert client.get("/api/features").json() == []
            assert client.get("/api/health").text == "ok"
            assert client.get("/api/adapters").status_code == 200
            assert client.get("/api/obstacles/info").status_code == 404
            assert client.get("/api/route_planner/info").status_code == 404
            assert client.get("/api/manual_flight/variants").status_code == 404
            assert client.get("/api/example_hello/hello").status_code == 404
            assert client.get("/").status_code == 200
            plugins = client.get("/api/plugins").json()["plugins"]
            assert {p["id"] for p in plugins} == {"obstacles", "route_planner",
                                                  "manual_flight", "example_hello"}
            assert all(p["state"] == "disabled" for p in plugins)
    finally:
        monkeypatch.undo()
        importlib.reload(module)


def test_toggle_endpoint_writes_config(monkeypatch, tmp_path):
    """``POST /api/plugins/<id>/enabled`` zapisuje stan w ``config.json``."""
    cfg = tmp_path / "config.json"
    monkeypatch.setenv("DRONESIM_CONFIG_FILE", str(cfg))
    import app.server as server

    module = importlib.reload(server)
    try:
        with TestClient(module.app) as client:
            answer = client.post("/api/plugins/example_hello/enabled",
                                 json={"enabled": False})
            assert answer.status_code == 200
            body = answer.json()
            assert body["enabled"] is False
            assert body["restart_required"] is True
            assert "restarcie" in body["message"]
            assert client.post("/api/plugins/nie_ma/enabled",
                               json={"enabled": False}).status_code == 404
        saved = json.loads(cfg.read_text(encoding="utf-8"))
        assert saved["features"]["example_hello"]["enabled"] is False
        # zmiana działa po „restarcie” (przeładowaniu modułu serwera)
        module = importlib.reload(server)
        states = {r.id: r.state for r in module.PLUGINS}
        assert states["example_hello"] == registry.STATE_DISABLED
        assert states["obstacles"] == registry.STATE_ENABLED
        with TestClient(module.app) as client:
            assert client.get("/api/example_hello/hello").status_code == 404
    finally:
        monkeypatch.undo()
        importlib.reload(module)
