"""Testy systemu wtyczek: ładowanie, zależności, izolacja błędów, przełączanie.

Testy nie polegają na działającym serwerze - budują aplikację w tym procesie
(``TestClient``) albo wołają rejestr bezpośrednio. Katalogi wtyczek tworzymy
w ``tmp_path``, więc nie ruszamy prawdziwego ``plugins/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.features import plugin_model, registry


def write_plugin(root: Path, plugin_id: str, **overrides) -> Path:
    """Utwórz wtyczkę w ``root/<id>`` z manifestem i opcjonalnym kodem."""
    folder = root / plugin_id
    (folder / "src").mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_id,
        "name": overrides.pop("name", plugin_id.title()),
        "version": overrides.pop("version", "1.0.0"),
        "description": overrides.pop("description", "testowa wtyczka"),
        "author": overrides.pop("author", "tester"),
        # domyślnie „wtyczka dla dowolnej wersji aplikacji” - helper nie może
        # wymagać wersji, której jeszcze nie ma (blokowałoby to wtyczkę)
        "requires_app": overrides.pop("requires_app", ">=0.1.0"),
        "requires": overrides.pop("requires", []),
        "extension_points": overrides.pop("extension_points", []),
    }
    manifest.update(overrides)
    (folder / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    return folder


# ------------------------------------------------------------------ manifest
def test_manifest_accepts_minimal_plugin(tmp_path):
    folder = write_plugin(tmp_path, "minimal")
    manifest = plugin_model.read_manifest(folder)
    assert manifest["id"] == "minimal"
    assert manifest["api_prefix"] == "/api/minimal"
    assert manifest["requires"] == []


@pytest.mark.parametrize("payload,message", [
    ({"id": "", "name": "x", "version": "1", "description": "d"}, "pole 'id'"),
    ({"id": "Zle Id", "name": "x", "version": "1", "description": "d"},
     "id 'Zle Id' niepoprawne"),
    ({"id": "ok", "name": "", "version": "1", "description": "d"}, "pole 'name'"),
    ({"id": "ok", "name": "x", "version": "", "description": "d"}, "pole 'version'"),
    ({"id": "ok", "name": "x", "version": "1"}, "pole 'description'"),
    ({"id": "ok", "name": "x", "version": "1", "description": "d",
      "requires": "obstacles"}, "pole 'requires'"),
    ({"id": "ok", "name": "x", "version": "1", "description": "d",
      "extension_points": ["nie_ma"]}, "nieznane punkty rozszerzeń"),
    ({"id": "ok", "name": "x", "version": "1", "description": "d",
      "requires": ["ok"]}, "nie może wymagać sama siebie"),
])
def test_manifest_rejects_bad_fields(payload, message):
    with pytest.raises(plugin_model.ManifestError) as info:
        plugin_model.validate_manifest(payload)
    assert message in str(info.value)


def test_manifest_reports_broken_json(tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "plugin.json").write_text("{ zły json", encoding="utf-8")
    with pytest.raises(plugin_model.ManifestError) as info:
        plugin_model.read_manifest(folder)
    assert "JSON" in str(info.value)


@pytest.mark.parametrize("constraint,expected", [
    (">=1.0.0", True), (">=1.1.0", False), ("==1.0.0", True),
    ("<2.0.0", True), ("", True), (">=0.9,<2.0", True), (">=1.0.1", False),
])
def test_version_constraints(constraint, expected):
    assert plugin_model.version_satisfies("1.0.0", constraint) is expected


# ---------------------------------------------------- odkrywanie i zależności
def test_discover_reads_builtin_and_external(tmp_path):
    write_plugin(tmp_path, "zeta")
    write_plugin(tmp_path, "alfa")
    records = registry.discover(builtin_root=tmp_path / "brak", external_root=tmp_path)
    assert [r.id for r in records] == ["alfa", "zeta"]
    assert all(r.source == "external" for r in records)


def test_discover_reports_broken_manifest_without_crashing(tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "plugin.json").write_text("{}", encoding="utf-8")
    write_plugin(tmp_path, "dobra")
    records = registry.discover(builtin_root=tmp_path / "brak", external_root=tmp_path)
    by_id = {r.id: r for r in records}
    assert by_id["broken"].state == registry.STATE_ERROR
    assert "pole 'id'" in by_id["broken"].error
    assert by_id["dobra"].state == registry.STATE_DISABLED   # jeszcze nietknięta


def test_dependencies_sorted_before_dependents(tmp_path):
    write_plugin(tmp_path, "aaa_dependent", requires=["zzz_base"])
    write_plugin(tmp_path, "zzz_base")
    records = registry.discover(builtin_root=tmp_path / "brak", external_root=tmp_path)
    ordered = [r.id for r in registry.sort_by_dependencies(records)]
    assert ordered.index("zzz_base") < ordered.index("aaa_dependent")


def test_missing_dependency_marks_error(tmp_path):
    write_plugin(tmp_path, "samotna", requires=["nie_ma"])
    write_plugin(tmp_path, "dobra")
    records = registry.discover(builtin_root=tmp_path / "brak", external_root=tmp_path)
    registry.sort_by_dependencies(records)
    by_id = {r.id: r for r in records}
    assert by_id["samotna"].state == registry.STATE_ERROR
    assert "nieistniejących" in by_id["samotna"].error
    assert by_id["dobra"].state != registry.STATE_ERROR


def test_cycle_marks_all_in_cycle_as_error(tmp_path):
    write_plugin(tmp_path, "pierwsza", requires=["druga"])
    write_plugin(tmp_path, "druga", requires=["pierwsza"])
    records = registry.discover(builtin_root=tmp_path / "brak", external_root=tmp_path)
    registry.sort_by_dependencies(records)
    for record in records:
        assert record.state == registry.STATE_ERROR
        assert "cykl" in record.error
