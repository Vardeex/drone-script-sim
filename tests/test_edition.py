"""Testy edycji wydania (``edition.json``) i trybu lekkiego w API.

Bez ``edition.json`` działa edycja standardowa - dokładnie jak dotąd (żadna
wtyczka ani opcja nie zmienia zachowania). Edycja ``for_potatoes`` startuje
w trybie lekkim i ma domyślnie wyłączone dodatki; użytkownik może je włączyć
w „Wtyczkach”/ustawieniach.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import edition
from app.features import registry
from app.server import app


@pytest.fixture()
def potatoes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Udawaj edycję ``for_potatoes`` (plik edition.json w katalogu tymczasowym)."""
    path = tmp_path / "edition.json"
    path.write_text(json.dumps({"edition": "for_potatoes"}), encoding="utf-8")
    monkeypatch.setenv("DRONESIM_EDITION_FILE", str(path))
    return path


def test_default_is_standard(monkeypatch: pytest.MonkeyPatch):
    """Brak pliku = edycja standardowa, tryb lekki nie jest wymuszany."""
    monkeypatch.delenv("DRONESIM_EDITION_FILE", raising=False)
    info = edition.info()
    assert info["edition"] == "standard"
    assert info["lite_default"] is False
    assert info["display_name"] == edition.__version__
    assert info["features"] == {"fpv": True, "realism": True,
                                "plan_line": True, "example_plugin": True}


def test_potatoes_edition(potatoes: Path):
    """Edycja for_potatoes: tryb lekki domyślnie, dodatki wyłączone."""
    info = edition.info()
    assert info["edition"] == "for_potatoes"
    assert info["lite_default"] is True
    assert info["display_name"] == f"{edition.__version__} for_potatoes"
    assert info["features"]["fpv"] is False
    assert info["features"]["realism"] is False
    assert info["features"]["plan_line"] is False
    assert info["features"]["example_plugin"] is False


def test_broken_file_falls_back_to_standard(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch):
    """Uszkodzony albo nieznany plik nie może zepsuć startu aplikacji."""
    path = tmp_path / "edition.json"
    path.write_text("{to nie jest json", encoding="utf-8")
    monkeypatch.setenv("DRONESIM_EDITION_FILE", str(path))
    assert edition.read_edition() == "standard"
    path.write_text(json.dumps({"edition": "cos-innego"}), encoding="utf-8")
    assert edition.read_edition() == "standard"


def test_plugins_enabled_by_default_only_in_standard(
        monkeypatch: pytest.MonkeyPatch, potatoes: Path):
    """example_hello: domyślnie włączona w standardzie, wyłączona w for_potatoes."""
    manifest = {"id": "example_hello", "enabled": True}
    monkeypatch.delenv("DRONESIM_EDITION_FILE", raising=False)
    assert registry.is_enabled(manifest, settings={}) is True
    monkeypatch.setenv("DRONESIM_EDITION_FILE", str(potatoes))
    assert registry.is_enabled(manifest, settings={}) is False
    # nadpisanie użytkownika (config.json) ma pierwszeństwo nad domyślną edycją
    assert registry.is_enabled(manifest,
                               settings={"example_hello": {"enabled": True}}) is True
    # inne wtyczki działają normalnie
    assert registry.is_enabled({"id": "obstacles"}, settings={}) is True


def test_api_edition_endpoint(potatoes: Path):
    """``/api/edition`` zwraca edycję i domyślne ustawienia dla interfejsu."""
    client = TestClient(app)
    data = client.get("/api/edition").json()
    assert data["edition"] == "for_potatoes"
    assert data["lite_default"] is True
    assert data["app_version"] == edition.__version__
    plugins = client.get("/api/plugins").json()
    assert plugins["edition"] == "for_potatoes"
    assert plugins["display_name"].endswith("for_potatoes")
