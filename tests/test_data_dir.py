"""Testy katalogu danych użytkownika (``DRONESIM_DATA_DIR``).

Wersja z git trzyma dane w katalogu projektu (jak dotąd). Wersja instalowana
ustawia zmienną środowiskową, więc loty, własne sceny i ``config.json`` leżą
w ``%LOCALAPPDATA%\\DroneSim`` i przeżywają aktualizację/deinstalację.

Ścieżki są liczone przy imporcie ``app.paths``, więc każdy przypadek sprawdzamy
w **osobnym podprocesie** (czyste środowisko, żadnych pozostałości z pytest).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: wypisuje rozwiązane ścieżki jako JSON (żeby test nie zgadywał)
PROBE = """
import json
from app import config, paths
from app.features.obstacles import store
print(json.dumps({
    "project_root": str(paths.PROJECT_ROOT),
    "data_root": str(paths.DATA_ROOT),
    "flights": str(paths.FLIGHTS_DIR),
    "uploads": str(paths.UPLOADS_DIR),
    "scenes_user": str(paths.SCENES_USER_DIR),
    "scenes_examples": str(store.scenes_root()),
    "store_user_dir": str(store.user_dir()),
    "config": str(config.config_path()),
}))
"""


def resolve_paths(**env_overrides) -> dict:
    """Uruchom ``PROBE`` w podprocesie i zwróć rozwiązane ścieżki."""
    env = dict(os.environ)
    env.pop("DRONESIM_DATA_DIR", None)
    env.pop("DRONESIM_CONFIG_FILE", None)
    env.update({key: str(value) for key, value in env_overrides.items()})
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=str(PROJECT_ROOT),
                            env=env, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return json.loads(result.stdout.decode("utf-8").strip().splitlines()[-1])


def test_default_data_dir_is_project_root():
    """Bez zmiennej środowiskowej dane są w katalogu projektu (zachowanie z gita)."""
    paths = resolve_paths()
    root = Path(paths["project_root"]).resolve()
    assert Path(paths["data_root"]).resolve() == root
    assert Path(paths["flights"]).resolve() == root / "flights"
    assert Path(paths["uploads"]).resolve() == root / "flights" / "_uploads"
    assert Path(paths["scenes_user"]).resolve() == root / "scenes" / "user"
    assert Path(paths["config"]).resolve() == root / "config.json"
    # sceny przykładowe zostają w projekcie (tylko do odczytu)
    assert Path(paths["scenes_examples"]).resolve() == root / "scenes"


def test_env_moves_user_data_to_chosen_dir(tmp_path: Path):
    """``DRONESIM_DATA_DIR`` przenosi loty, własne sceny i config do katalogu danych."""
    data = tmp_path / "drone-data"
    paths = resolve_paths(DRONESIM_DATA_DIR=data)
    root = Path(paths["project_root"]).resolve()
    assert Path(paths["data_root"]).resolve() == data.resolve()
    assert Path(paths["flights"]).resolve() == data / "flights"
    assert Path(paths["uploads"]).resolve() == data / "flights" / "_uploads"
    assert Path(paths["scenes_user"]).resolve() == data / "scenes" / "user"
    assert Path(paths["store_user_dir"]).resolve() == data / "scenes" / "user"
    assert Path(paths["config"]).resolve() == data / "config.json"
    # kod aplikacji i sceny przykładowe nadal w katalogu programu
    assert Path(paths["scenes_examples"]).resolve() == root / "scenes"
    # nic nie powstaje w katalogu projektu
    assert Path(paths["flights"]).resolve() != root / "flights"


def test_config_env_wins_over_data_dir(tmp_path: Path):
    """``DRONESIM_CONFIG_FILE`` (testy/zaawansowane) ma pierwszeństwo."""
    explicit = tmp_path / "moj-config.json"
    paths = resolve_paths(DRONESIM_DATA_DIR=tmp_path / "dane",
                          DRONESIM_CONFIG_FILE=explicit)
    assert Path(paths["config"]).resolve() == explicit.resolve()
    assert Path(paths["flights"]).resolve() == (tmp_path / "dane" / "flights").resolve()
