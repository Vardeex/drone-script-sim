"""Testy funkcji ``obstacles``: sceny, API, zapis sceny z lotem, wyłączanie funkcji."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.features.obstacles import store
from app.features.obstacles.model import Obstacle, Scene, SceneError


@pytest.fixture()
def scenes_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sceny w katalogu tymczasowym (przykładowe + użytkownika)."""
    root = tmp_path / "scenes"
    root.mkdir()
    (root / store.USER_DIR_NAME).mkdir()
    monkeypatch.setattr(store, "SCENES_DIR", root)
    return root


def test_scene_roundtrip(scenes_tmp: Path):
    scene = Scene(name="Pokój", room=(400, 400, 250), obstacles=[
        Obstacle(kind="box", name="szafa", position=(100, 50, 100), size=(60, 120, 200)),
        Obstacle(kind="gate", name="bramka", position=(200, 0, 80), size=(120, 5, 120),
                 opening=(90, 90), yaw_deg=30),
    ])
    saved = store.save_scene(scene, name="pokoj")
    assert saved["name"] == "pokoj"
    loaded = store.load_scene("pokoj")
    assert loaded.name == "Pokój"
    assert loaded.room == (400.0, 400.0, 250.0)
    assert [o.kind for o in loaded.obstacles] == ["box", "gate"]
    assert loaded.obstacles[1].opening == (90.0, 90.0)
    assert loaded.obstacles[1].yaw_deg == pytest.approx(30.0)
    assert (scenes_tmp / "user" / "pokoj.json").exists()


def test_user_scene_overrides_example_and_can_be_deleted(scenes_tmp: Path):
    example = scenes_tmp / "tor.json"
    example.write_text(json.dumps(Scene(name="Tor", obstacles=[]).as_dict()), encoding="utf-8")
    assert store.load_scene("tor").name == "Tor"
    store.save_scene(Scene(name="Mój tor", obstacles=[]), name="tor")
    assert store.load_scene("tor").name == "Mój tor"
    assert store.delete_scene("tor") is True
    assert store.load_scene("tor").name == "Tor"          # wraca przykład z repo
    assert store.delete_scene("tor") is False             # przykładów nie usuwamy


def test_invalid_scene_name_rejected(scenes_tmp: Path):
    for bad in ("../etc", "a/b", "x" * 90, "  ..  ", "a:b"):
        try:
            store.save_scene(Scene(), name=bad)
        except SceneError:
            continue
        raise AssertionError(f"nazwa {bad!r} została przyjęta")


def test_empty_name_falls_back_to_scene_name(scenes_tmp: Path):
    saved = store.save_scene(Scene(name="Moja scena"), name="")
    assert saved["name"] == "Moja scena"
    assert store.load_scene("Moja scena").name == "Moja scena"


def test_list_scenes_marks_examples_and_user(scenes_tmp: Path):
    (scenes_tmp / "a.json").write_text(json.dumps(Scene(name="A").as_dict()), encoding="utf-8")
    store.save_scene(Scene(name="B"), name="b")
    items = store.list_scenes()
    assert [(i["name"], i["user"]) for i in items] == [("a", False), ("b", True)]


def test_scene_validation_errors():
    with pytest.raises(SceneError):
        Obstacle(kind="kula")
    with pytest.raises(SceneError):
        Obstacle(kind="box", size=(10, 0, 10))
    with pytest.raises(SceneError):
        Scene.from_dict({"obstacles": "nie-lista"})
