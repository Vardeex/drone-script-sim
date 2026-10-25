"""Testy „Lotu ręcznego”: sesja RC, nagrywanie i generowanie skryptu.

Sedno: **nagranie → wygenerowany skrypt → uruchomienie w symulatorze → tor
zgodny z nagraniem**. Oczekiwania liczymy z fizyki symulatora (profil Tello:
RC 100 = 50 cm/s poziomo, 90 °/s obrotu), a nie z wyniku programu:

* ``rc(0, 50, 0, 0, 0.2)`` = 25 cm/s × 0,2 s = **5 cm** do przodu,
* ``rc(50, 0, 0, 0, 0.2)`` = 5 cm w prawo, czyli ``y = -5`` (oś ``y`` = lewo),
* ``rc(0, 0, 0, 50, 0.2)`` = 45 °/s × 0,2 s = **9°** obrotu w prawo.

Wariant (a) musi trafić w punkty kontrolne ≤ 5 cm, wariant (b) w punkty
zatrzymań ≤ 20 cm (uproszczenie: osie zamiast skosu, pomijane ruchy < 20 cm).
"""

from __future__ import annotations

import math
import re

import pytest

from app import runner
from app.features.manual_flight import codegen, session as manual


@pytest.fixture(autouse=True)
def _reset_session():
    """Każdy test zaczyna bez sesji (rejestr jest globalny)."""
    manual.close_session()
    yield
    manual.close_session()


def record_scenario(speed: int = 50) -> "manual.ManualSession":
    """Nagraj prosty, realistyczny lot: ruchy po kilkadziesiąt cm i obrót.

    Czasy dobrane tak, żeby każdy ruch był wyraźnie dłuższy niż limit 20 cm
    wariantu uproszczonego (50 RC = 25 cm/s):
    """
    current = manual.ManualSession(speed=speed)
    current.start()                       # 80 cm
    for _ in range(8):                    # przód 0,8 s = 20 cm... (25 cm/s)
        current.rc(0, 100, 0, 0, 0.1)     # 100 RC = 50 cm/s -> 5 cm na odcinek
    for _ in range(3):
        current.rc(0, 0, 0, 0, 0.1)       # stop (0,3 s)
    for _ in range(4):                    # obrót w prawo: 40° (90°/s x 0,4 s)
        current.rc(0, 0, 0, 100, 0.1)
    for _ in range(6):                    # przód 60 cm po nowym kursie
        current.rc(0, 100, 0, 0, 0.1)
    for _ in range(3):
        current.rc(0, 0, 0, 0, 0.1)       # stop
    for _ in range(4):                    # w górę 20 cm (50 cm/s x 0,4 s)
        current.rc(0, 0, 100, 0, 0.1)
    for _ in range(3):
        current.rc(0, 0, 0, 0, 0.1)       # stop
    current.land()
    return current


# ------------------------------------------------------------------ fizyka RC
def test_forward_matches_profile():
    """RC 50 przez 0,2 s = 25 cm/s × 0,2 s = 5 cm (profil Tello)."""
    current = manual.ManualSession()
    current.start()
    assert current.state()["z"] == pytest.approx(80.0, abs=0.1)
    first = current.rc(0, 50, 0, 0, 0.2)
    second = current.rc(0, 50, 0, 0, 0.2)
    assert first["x"] == pytest.approx(5.0, abs=0.2)
    assert second["x"] == pytest.approx(10.0, abs=0.3)
    assert first["y"] == pytest.approx(0.0, abs=1e-6)


def test_right_is_minus_y():
    """``lr`` dodatnie = prawo; w układzie projektu prawo to ``-y``."""
    current = manual.ManualSession()
    current.start()
    state = current.rc(50, 0, 0, 0, 0.2)
    assert state["y"] == pytest.approx(-5.0, abs=0.2)
    assert state["x"] == pytest.approx(0.0, abs=1e-6)


def test_yaw_positive_turns_clockwise():
    """``yaw`` dodatnie = obrót w prawo (45 °/s przy RC 50)."""
    current = manual.ManualSession()
    current.start()
    state = current.rc(0, 0, 0, 50, 0.2)
    assert state["yaw"] == pytest.approx(9.0, abs=0.3)      # get_yaw: + = prawo


def test_up_down_changes_height():
    """``ud`` dodatnie = wyżej (50 cm/s przy RC 100)."""
    current = manual.ManualSession()
    current.start()
    up = current.rc(0, 0, 100, 0, 0.2)
    assert up["z"] == pytest.approx(90.0, abs=0.3)
    down = current.rc(0, 0, -100, 0, 0.2)
    assert down["z"] == pytest.approx(80.0, abs=0.5)


def test_dt_is_limited():
    """Zbyt duży ``dt`` jest przycinany do 0,3 s (ochrona przed skokiem drona)."""
    current = manual.ManualSession()
    current.start()
    state = current.rc(0, 100, 0, 0, 5.0)          # 5 s -> tylko 0,3 s = 15 cm
    assert state["x"] == pytest.approx(15.0, abs=0.5)


def test_rc_on_ground_does_nothing():
    """RC przed startem nie rusza dronem (jak w symulatorze skryptów)."""
    current = manual.ManualSession()
    state = current.rc(0, 100, 0, 0, 0.2)
    assert state["x"] == pytest.approx(0.0, abs=1e-6)
    assert state["flying"] is False


def test_speed_is_clamped():
    """Prędkość manewrowa w zakresie 10-100 (jak ``set_speed`` Tello)."""
    current = manual.ManualSession()
    assert current.set_speed(5)["speed"] == 10
    assert current.set_speed(500)["speed"] == 100
    assert current.set_speed(60)["speed"] == 60


# ------------------------------------------------- nagranie -> skrypt -> tor lotu
def _min_distance(samples, point) -> float:
    """Najmniejszy dystans toru lotu od punktu (cm)."""
    return min(math.dist((s["x"], s["y"], s["z"]), point) for s in samples)


def _run_script(source: str):
    result = runner.run_script(source, "manual_flight.py")
    assert result.status == "ok", [e["message"] for e in result.flight.errors][:2]
    return result.flight.samples


def test_recording_has_control_and_stop_points():
    """Nagranie daje punkty kontrolne (zmiany RC) i punkty zatrzymań."""
    current = record_scenario()
    controls = current.control_points()
    stops = current.stop_points()
    assert len(controls) >= 5, controls
    assert stops, "brak punktów zatrzymań w nagraniu"
    # scenariusz: 80 cm na 80 cm wysokości, więc pierwszy punkt kontrolny jest w locie
    assert all(point[3] > 50 for point in controls), controls


@pytest.mark.parametrize("variant,limit", [("rc", 5.0), ("simple", 20.0)])
def test_generated_script_matches_recording(variant, limit):
    """Wariant (a) ≤ 5 cm w punktach kontrolnych, (b) ≤ 20 cm w zatrzymaniach."""
    current = record_scenario()
    points = (current.control_points() if variant == "rc"
              else current.stop_points())
    assert points, f"brak punktów do porównania dla wariantu {variant}"
    source = codegen.generate(current.recording, variant=variant, speed=current.speed)
    samples = _run_script(source)
    for moment, x, y, z in points:
        distance = _min_distance(samples, (x, y, z))
        assert distance <= limit, (
            f"wariant {variant}: punkt t={moment:.1f} ({x:.1f}, {y:.1f}, {z:.1f}) "
            f"oddalony o {distance:.1f} cm (limit {limit} cm)")


def test_simple_variant_respects_tello_limits():
    """Wygenerowany wariant (b) używa tylko komend w limitach Tello."""
    current = record_scenario()
    source = codegen.generate(current.recording, variant="simple", speed=current.speed)
    moves = re.findall(r"tello\.(move_\w+|rotate_\w+)\((\d+)\)", source)
    assert moves, source
    for name, value in moves:
        number = int(value)
        if name.startswith("move_"):
            assert 20 <= number <= 500, f"{name}({number}) poza 20-500"
        else:
            assert 1 <= number <= 360, f"{name}({number}) poza 1-360"


def test_rc_variant_uses_send_rc_control():
    """Wariant (a) odtwarza nagranie przez ``send_rc_control`` + ``time.sleep``."""
    current = record_scenario()
    source = codegen.generate(current.recording, variant="rc", speed=current.speed)
    assert "send_rc_control" in source
    assert "time.sleep" in source
    assert "takeoff()" in source and "land()" in source
    # złączone odcinki: skrypt jest krótszy niż liczba nagranych segmentów
    calls = source.count("send_rc_control")
    assert 0 < calls < len(current.recording)


def test_unknown_variant_rejected():
    """Nieznany wariant to czytelny błąd (nie cichy fallback)."""
    current = record_scenario()
    with pytest.raises(ValueError):
        codegen.generate(current.recording, variant="inny")


# ---------------------------------------------------------------------- API
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.server import app

    with TestClient(app) as test_client:
        yield test_client


def test_api_full_cycle(client):
    """Start -> RC -> stan -> nagranie -> skrypt -> lądowanie -> stop."""
    assert client.post("/api/manual_flight/start", json={"speed": 50}).status_code == 200
    started = client.post("/api/manual_flight/takeoff").json()
    assert started["flying"] is True and started["z"] == pytest.approx(80.0, abs=0.1)

    state = None
    for _ in range(10):
        state = client.post("/api/manual_flight/rc",
                            json={"fb": 100, "dt": 0.1}).json()
    assert state["x"] == pytest.approx(50.0, abs=1.0)   # 10 x 0.1 s x 50 cm/s

    recording = client.get("/api/manual_flight/recording").json()
    assert recording["segments"] == 10
    assert recording["control_points"]

    script = client.post("/api/manual_flight/script", json={"variant": "rc"}).json()
    assert "send_rc_control(0, 100, 0, 0)" in script["source"]
    simple = client.post("/api/manual_flight/script",
                         json={"variant": "simple"}).json()
    assert "move_forward(50)" in simple["source"]       # 10 x 5 cm = 50 cm

    assert client.post("/api/manual_flight/land").json()["flying"] is False
    assert client.post("/api/manual_flight/stop").json()["closed"] is True
    # po zamknięciu sesji endpointy zwracają 404 z czytelnym komunikatem
    response = client.get("/api/manual_flight/state")
    assert response.status_code == 404
    assert "uruchomiony" in response.json()["detail"]


def test_api_variants_and_errors(client):
    """Lista wariantów + błędy: brak sesji, brak nagrania, zły wariant."""
    variants = client.get("/api/manual_flight/variants").json()["variants"]
    assert {item["id"] for item in variants} == {"rc", "simple"}
    assert client.post("/api/manual_flight/script",
                       json={"variant": "rc"}).status_code == 404   # brak sesji

    client.post("/api/manual_flight/start", json={})
    empty = client.post("/api/manual_flight/script", json={"variant": "rc"})
    assert empty.status_code == 400
    assert "nagrania" in empty.json()["detail"]

    client.post("/api/manual_flight/takeoff")
    client.post("/api/manual_flight/rc", json={"fb": 100, "dt": 0.1})
    bad = client.post("/api/manual_flight/script", json={"variant": "xyz"})
    assert bad.status_code == 400 and "xyz" in bad.json()["detail"]


def test_api_speed_and_recording_toggles(client):
    """Prędkość i nagrywanie zmieniają stan sesji."""
    client.post("/api/manual_flight/start", json={"speed": 30})
    assert client.post("/api/manual_flight/speed", json={"speed": 80}).json()["speed"] == 80
    assert client.post("/api/manual_flight/record",
                       json={"enabled": False}).json()["recording"] is False
    client.post("/api/manual_flight/takeoff")
    client.post("/api/manual_flight/rc", json={"fb": 100, "dt": 0.1})
    # nagrywanie wyłączone -> brak segmentów
    assert client.get("/api/manual_flight/recording").json()["segments"] == 0


def test_api_warns_when_close_to_obstacle(client):
    """Ostrzeżenie o zbliżeniu liczy się tak samo jak w analizie lotu."""
    scene = {"obstacles": [{
        "id": "wall", "kind": "box", "name": "ściana",
        "position": [100, 0, 80], "size": [20, 200, 200], "yaw_deg": 0,
    }]}
    client.post("/api/manual_flight/start",
                json={"speed": 50, "scene": scene, "margin_cm": 20})
    client.post("/api/manual_flight/takeoff")
    state = None
    for _ in range(8):                     # 8 x 5 cm = 40 cm przód
        state = client.post("/api/manual_flight/rc",
                            json={"fb": 100, "dt": 0.1}).json()
    # ściana ma 20 cm grubości w x=100, więc jej przednia ściana to x=90;
    # dron na x=40 ma do niej 50 cm - jeszcze bez ostrzeżenia
    assert state["warning"] is None, state
    for _ in range(6):                     # +30 cm -> x=70, 20 cm do ściany
        state = client.post("/api/manual_flight/rc",
                            json={"fb": 100, "dt": 0.1}).json()
    assert state["warning"] is not None, state
    assert state["clearance"] is not None and state["clearance"] <= 20.0
