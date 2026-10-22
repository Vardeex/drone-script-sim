"""Test: funkcję ``obstacles`` można wyłączyć jednym ustawieniem w konfiguracji."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.features import registry
from app.server import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _reload_server_with_config(monkeypatch: pytest.MonkeyPatch, tmp_path, payload: dict):
    """Udawaj restart aplikacji z podanym ``config.json``."""
    import importlib

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DRONESIM_CONFIG_FILE", str(cfg))
    import app.server as server

    module = importlib.reload(server)
    return module


def test_config_feature_disabled(monkeypatch, tmp_path):
    """Funkcja wyłączona w konfiguracji nie ma routera, a aplikacja działa dalej."""
    module = _reload_server_with_config(
        monkeypatch, tmp_path, {"features": {"obstacles": {"enabled": False}}})
    try:
        with TestClient(module.app) as client:
            ids = [f["id"] for f in client.get("/api/features").json()]
            assert "obstacles" not in ids, f"funkcja obstacles wciąż włączona: {ids}"
            assert client.get("/api/obstacles/info").status_code == 404
            assert client.get("/api/obstacles/scenes").status_code == 404
            # aplikacja działa normalnie: loty, adaptery, historia
            assert client.get("/api/health").text == "ok"
            assert client.get("/api/adapters").status_code == 200
            started = client.post("/api/run", json={"source": "print('ok')", "save": False})
            assert started.status_code == 200
    finally:
        monkeypatch.undo()
        import importlib

        importlib.reload(module)


def test_config_feature_enabled_reports_ui(monkeypatch, tmp_path):
    """Włączona funkcja jest na liście razem z manifestem UI."""
    module = _reload_server_with_config(monkeypatch, tmp_path, {})
    try:
        with TestClient(module.app) as client:
            features = client.get("/api/features").json()
            by_id = {f["id"]: f for f in features}
            assert "obstacles" in by_id, [f["id"] for f in features]
            panel = by_id["obstacles"]["ui"]["panel"]
            assert panel.endswith("panel.js")
            assert client.get("/api/obstacles/info").status_code == 200
    finally:
        monkeypatch.undo()
        import importlib

        importlib.reload(module)


def test_registry_helpers(monkeypatch):
    settings = {"demo": {"enabled": False}}
    manifest = {"id": "demo", "enabled": True}
    assert registry.is_enabled(manifest, settings) is False
    assert registry.is_enabled(manifest, {}) is True
    assert registry.is_enabled({"id": "x", "enabled": False}, {}) is False
    assert config.feature_settings("demo") == {}
