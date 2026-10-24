"""Testy Mission Padów (Tello EDU) w symulatorze - geometria liczona ręcznie.

Założenia modelu (patrz :mod:`app.features.obstacles.mission_pads` i README):
promień wykrywania 30 cm od środka maty, wysokość 30-120 cm nad matą.

Wszystkie oczekiwane wartości poniżej wynikają z geometrii sceny, nie z
odczytów symulatora.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import runner
from app.features.obstacles import mission_pads
from app.features.obstacles.model import Obstacle, Scene, SceneError
from app.server import app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SCENE_PATH = ROOT / "scenes" / "mission_pads.json"


def load_scene() -> dict:
    """Scena ``mission_pads`` jako słownik (tak jak wysyła ją UI)."""
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


def run(source: str, scene: dict | None = None, max_sim_time: float = 600):
    """Uruchom skrypt ze sceną mat (domyślnie sceną z ``scenes/mission_pads.json``)."""
    settings = {"max_sim_time": max_sim_time}
    if scene is not None:
        settings["scene"] = scene
    return runner.run_script(source, "pads.py", extra_settings=settings)


def stdout_text(result) -> str:
    return "".join(line if isinstance(line, str) else line.get("text", "")
                   for line in result.stdout or [])


def sample_at_last_move(result) -> dict:
    """Próbka telemetrii w chwili zakończenia ostatniego ruchu w powietrzu.

    Koniec lotu to ``land`` - telemetria lądowania schodzi do zera, więc
    pozycję końcową bierzemy z ``t_end`` ostatniego zdarzenia ruchu
    (``INTERESTING`` = komendy, które przemieszczają drona).
    """
    interesting = {"go_xyz_speed", "go_xyz_speed_mid", "curve_xyz_speed_mid",
                   "move_up", "move_down", "move_forward", "move_back",
                   "move_left", "move_right"}
    moves = [e for e in result.flight.events
             if e.get("command") in interesting and e.get("status") in ("ok", "warning")]
    assert moves, "brak zdarzeń ruchu w locie"
    moment = float(moves[-1]["t_end"])
    samples = [s for s in result.flight.samples if s["t"] <= moment + 1e-6]
    assert samples
    return samples[-1]


# ------------------------------------------------------------------- model
def test_scene_has_four_pads():
    """Scena wzorcowa: cztery maty o numerach 1-4, wszystkie na podłodze."""
    pads = mission_pads.scene_pads(load_scene())
    assert [pad["pad_id"] for pad in pads] == [1, 2, 3, 4]
    assert all(pad["position"][2] == 0 for pad in pads)


def test_pad_serialization_roundtrip():
    """``pad_id`` przechodzi przez JSON sceny bez zmian."""
    scene = Scene.from_dict(load_scene())
    pad = scene.by_id("pad-4")
    assert pad is not None and pad.pad_id == 4
    again = Scene.from_dict(scene.as_dict()).by_id("pad-4")
    assert again is not None and again.pad_id == 4


def test_pad_id_must_be_1_to_8():
    """Numer maty spoza 1-8 to błąd walidacji sceny."""
    for bad in (0, 9, -1):
        with pytest.raises(SceneError):
            Obstacle(kind="mission_pad", pad_id=bad)


def test_pads_are_not_obstacles():
    """Mata nie bierze udziału w kolizjach (dron może nad nią wisieć)."""
    scene = Scene.from_dict(load_scene())
    assert scene.solids() == []


def test_detection_radius_and_height_from_geometry():
    """Granice wykrywania: promień 30 cm, wysokość 30-120 cm (dokładnie)."""
    pad = {"pad_id": 1, "position": [0, 0, 0], "yaw_deg": 0}
    inside = mission_pads.DETECTION_RADIUS_CM - 1
    assert mission_pads.visible_pad((inside, 0, 60), [pad]) is not None
    assert mission_pads.visible_pad((inside + 2, 0, 60), [pad]) is None
    low = mission_pads.DETECTION_MIN_HEIGHT_CM
    high = mission_pads.DETECTION_MAX_HEIGHT_CM
    assert mission_pads.visible_pad((0, 0, low), [pad]) is not None
    assert mission_pads.visible_pad((0, 0, high), [pad]) is not None
    assert mission_pads.visible_pad((0, 0, low - 2), [pad]) is None
    assert mission_pads.visible_pad((0, 0, high + 2), [pad]) is None


def test_nearest_pad_wins():
    """Przy dwóch matach w zasięgu kamera czyta bliższą ``(0,0)``."""
    near = {"pad_id": 2, "position": [20, 0, 0], "yaw_deg": 0}
    far = {"pad_id": 3, "position": [-20, 0, 0], "yaw_deg": 0}
    found = mission_pads.visible_pad((5, 0, 60), [far, near])
    assert found is not None and found["pad_id"] == 2


def test_pad_offset_uses_pad_rotation():
    """Obrót maty o 90° (w prawo): punkt świata ``+Y`` to ``-X`` w układzie maty."""
    pad = {"pad_id": 4, "position": [120, 120, 0], "yaw_deg": 90}
    # dron 20 cm na lewo od środka maty w świecie: (120, 140)
    offset = mission_pads.pad_offset((120, 140, 60), 0.0, pad)
    assert offset[0] == pytest.approx(20.0, abs=1e-6)   # przód maty = +Y świata
    assert offset[1] == pytest.approx(0.0, abs=1e-6)
    assert offset[2] == pytest.approx(60.0, abs=1e-6)


def test_pad_target_world_inverts_offset():
    """``pad_target_world`` jest odwrotnością ``pad_offset``."""
    pad = {"pad_id": 4, "position": [120, 120, 0], "yaw_deg": 90}
    target = mission_pads.pad_target_world(pad, (30, -10, 60))
    offset = mission_pads.pad_offset(target, 0.0, pad)
    assert offset == pytest.approx((30, -10, 60), abs=1e-6)


# ------------------------------------------------------- testy przez sandbox
DETECTION = """
from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.set_speed(40)
{body}
tello.land()
"""


def test_detection_off_by_default():
    """Bez ``enable_mission_pads`` Tello nie wykrywa mat (jak prawdziwy EDU)."""
    result = run(DETECTION.format(body="print('MID', tello.get_mission_pad_id())"),
                 load_scene())
    assert result.status == "ok", result.flight.errors
    assert "MID -1" in stdout_text(result)


def test_detects_pad_above_start():
    """Dron nad m1 (0,0) na 80 cm: ``mid = 1``, odległości (0, 0, 80)."""
    body = """
tello.enable_mission_pads()
print('MID', tello.get_mission_pad_id())
print('D', tello.get_mission_pad_distance_x(), tello.get_mission_pad_distance_y(),
      tello.get_mission_pad_distance_z())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    out = stdout_text(result)
    assert "MID 1" in out
    # geometria: dron nad środkiem maty, wysokość = takeoff 80 cm, mata na z = 0
    assert "D 0 0 80" in out


def test_no_detection_outside_radius():
    """60 cm od środka maty (poza zasięgiem 30 cm) - brak wykrywania."""
    body = """
tello.enable_mission_pads()
tello.move_forward(60)
print('MID', tello.get_mission_pad_id())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    assert "MID -1" in stdout_text(result)


def test_go_xyz_speed_mid_reaches_pad_point():
    """``go 0 0 60 ... m2`` kończy lot 60 cm nad środkiem m2 (120, 0).

    Na początku dron widzi m1 (jest nad nią), ale m2 jest 120 cm dalej - poza
    zasięgiem. Lecimy więc 90 cm ``move_forward``: dron jest wtedy 30 cm przed
    m2, czyli dokładnie na granicy zasięgu m2 (i 90 cm od m1 - już nie widzi m1).
    """
    body = """
tello.enable_mission_pads()
tello.move_forward(90)                   # 30 cm przed m2 (x = 90)
tello.go_xyz_speed_mid(0, 0, 60, 40, 2)  # nad m2, 60 cm nad matą
print('MID', tello.get_mission_pad_id())
print('D', tello.get_mission_pad_distance_x(), tello.get_mission_pad_distance_y(),
      tello.get_mission_pad_distance_z())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    out = stdout_text(result)
    assert "MID 2" in out
    assert "D 0 0 60" in out
    # telemetria: punkt (120, 0, 60) - z pozycji maty w scenie
    last = sample_at_last_move(result)
    assert last["x"] == pytest.approx(120, abs=1.0)
    assert last["y"] == pytest.approx(0, abs=1.0)
    assert last["z"] == pytest.approx(60, abs=1.0)


def test_go_xyz_speed_mid_uses_pad_rotation():
    """Mata 4 obrócona o 90°: punkt ``(40, 0)`` w jej układzie to ``+Y`` świata."""
    body = """
tello.enable_mission_pads()
tello.go_xyz_speed_mid(0, 0, 60, 40, 1)
tello.move_forward(90)                   # 90 cm przed m1
tello.move_forward(30)                   # nad m2 (120, 0)
tello.go_xyz_speed_mid(0, 0, 60, 40, 2)
tello.move_back(60)                      # 60 cm przed m1
tello.move_back(60)                      # nad m1
tello.move_left(60)                      # 60 cm w lewo od m1
tello.move_left(60)                      # nad m3 (0, 120)
tello.go_xyz_speed_mid(0, 0, 60, 40, 3)
tello.move_forward(90)                   # 90 cm przed m3 -> 30 cm od m4
tello.go_xyz_speed_mid(40, 0, 60, 40, 4)  # 40 cm "przód m4" = +Y świata
print('POS', tello.get_mission_pad_id(), tello.get_mission_pad_distance_x(),
      tello.get_mission_pad_distance_y())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    last = sample_at_last_move(result)
    # m4 leży w (120, 120) i jest obrócona o 90°, więc jej przód to +Y świata,
    # czyli cel = (120, 120 + 40) = (120, 160) - z geometrii sceny.
    assert last["x"] == pytest.approx(120, abs=2.0)
    assert last["y"] == pytest.approx(160, abs=2.0)
    assert last["z"] == pytest.approx(60, abs=1.0)


def test_go_xyz_speed_mid_fails_when_pad_not_visible():
    """Lot do maty spoza zasięgu kończy się błędem (jak prawdziwe Tello)."""
    body = """
tello.enable_mission_pads()
tello.go_xyz_speed_mid(0, 0, 60, 40, 3)
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "error"
    message = " ".join(str(e.get("message", "")) for e in result.flight.errors)
    assert "m3" in message and "widziana" in message


def test_go_xyz_speed_mid_requires_detection_enabled():
    """Bez ``enable_mission_pads`` komendy ``*_mid`` są odrzucane."""
    result = run(DETECTION.format(body="tello.go_xyz_speed_mid(0, 0, 60, 40, 1)"),
                 load_scene())
    assert result.status == "error"
    message = " ".join(str(e.get("message", "")) for e in result.flight.errors)
    assert "enable_mission_pads" in message


def test_unknown_pad_number_rejected():
    """Maty o numerze 9 nie ma w SDK (1-8)."""
    body = """
tello.enable_mission_pads()
tello.go_xyz_speed_mid(0, 0, 60, 40, 9)
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "error"
    message = " ".join(str(e.get("message", "")) for e in result.flight.errors)
    assert "1-8" in message


def test_detection_direction_validation():
    """Kierunek wykrywania: tylko 0, 1, 2 (``mdirection``)."""
    body = """
tello.enable_mission_pads()
tello.set_mission_pad_detection_direction(0)
print('OK', tello.get_mission_pad_id())
tello.set_mission_pad_detection_direction(5)
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "error"
    assert "OK 1" in stdout_text(result)
    message = " ".join(str(e.get("message", "")) for e in result.flight.errors)
    assert "0, 1 lub 2" in message


def test_disable_mission_pads():
    """Po ``disable_mission_pads`` dron przestaje widzieć maty."""
    body = """
tello.enable_mission_pads()
print('ON', tello.get_mission_pad_id())
tello.disable_mission_pads()
print('OFF', tello.get_mission_pad_id())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    out = stdout_text(result)
    assert "ON 1" in out and "OFF -1" in out


def test_no_scene_means_no_pads():
    """Bez sceny mat nie ma - wykrywanie włączone, ale ``mid = -1``."""
    body = """
tello.enable_mission_pads()
print('MID', tello.get_mission_pad_id())
"""
    result = run(DETECTION.format(body=body))
    assert result.status == "ok", result.flight.errors
    assert "MID -1" in stdout_text(result)


# --------------------------------------------------------------- API scen
@pytest.fixture(scope="module")
def client():
    """Klient testowy aplikacji (własny - moduł nie zależy od innych testów)."""
    with TestClient(app) as test_client:
        yield test_client


def test_api_scene_and_preset(client):
    """Scena ``mission_pads`` jest widoczna przez API, preset tworzy matę."""
    scene = client.get("/api/obstacles/scenes/mission_pads")
    assert scene.status_code == 200, scene.text
    assert [o["pad_id"] for o in scene.json()["obstacles"]] == [1, 2, 3, 4]
    preset = client.get("/api/obstacles/presets/mission_pad").json()
    assert preset["kind"] == "mission_pad" and preset["size"] == [30.0, 30.0, 1.0]


def test_api_rejects_pad_id_out_of_range(client):
    """Numer maty spoza 1-8 odrzuca walidacja sceny (HTTP 400)."""
    bad = client.post("/api/obstacles/validate", json={"obstacles": [
        {"kind": "mission_pad", "pad_id": 9, "position": [0, 0, 0],
         "size": [30, 30, 1]}]})
    assert bad.status_code == 400
    good = client.post("/api/obstacles/validate", json={"obstacles": [
        {"kind": "mission_pad", "pad_id": 7, "position": [0, 0, 0],
         "size": [30, 30, 1]}]})
    assert good.status_code == 200 and good.json()["obstacles"] == 1


def test_example_mission_pads_demo_runs():
    """Przykład ``examples/mission_pads_demo.py`` przechodzi przez 4 maty."""
    source = (ROOT / "examples" / "mission_pads_demo.py").read_text(encoding="utf-8")
    result = runner.run_script(source, "mission_pads_demo.py",
                               extra_settings={"scene": load_scene(), "max_sim_time": 600})
    assert result.status == "ok", [e["message"] for e in result.flight.errors][:2]
    out = stdout_text(result)
    for pad_id in (1, 2, 3, 4):
        assert f"m{pad_id} x=0 y=0 z=60" in out, out[:400]
    assert "na końcu: 4" in out
    """Powyżej 120 cm nad matą kamera nie czyta kodu."""
    body = """
tello.enable_mission_pads()
tello.move_up(60)                       # 80 + 60 = 140 cm nad matą
print('MID', tello.get_mission_pad_id())
"""
    result = run(DETECTION.format(body=body), load_scene())
    assert result.status == "ok", result.flight.errors
    assert "MID -1" in stdout_text(result)
