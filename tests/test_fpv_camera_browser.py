"""Testy przeglądarkowe kamery FPV („Z drona”).

Kamera ma być **przytwierdzona do drona**: pozycja = pozycja drona + obrót
kursem · przesunięcie do obiektywu (przód 25 mm, 12 mm nad dolną krawędzią
korpusu, PRAWDZIWA skala), kierunek patrzenia = kurs drona, poziomo.
Przełącznik „Rozmiar ×3/×5/×10” nie może ruszać kamery, a model drona nie może
zasłaniać widoku. Sprawdzamy to w kilku chwilach lotu (start, wznoszenie,
zakręt, lądowanie, przewinięcie wstecz), w trybie pełnym i lekkim.
"""

from __future__ import annotations

import math
import subprocess
import sys
import time
import urllib.request

import pytest

from tests.proc_helpers import kill_tree, spawn
from tests.test_route_planner_browser import TIMEOUT_MS, _free_port

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

pytestmark = pytest.mark.browser

#: przesunięcie obiektywu w układzie modelu drona (metry; +X = przód)
LENS_FORWARD_M = 0.025
LENS_HEIGHT_M = 0.012
#: tolerancje z zadania
POSITION_TOLERANCE_M = 0.01        # ±1 cm
HEADING_TOLERANCE_DEG = 1.0        # ±1°

FLIGHT = """from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.move_up(60)
tello.move_forward(120)
tello.rotate_clockwise(90)
tello.move_forward(120)
tello.rotate_counter_clockwise(45)
tello.move_up(40)
tello.land()
"""


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    process = spawn(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except Exception:                       # noqa: BLE001 - czekamy na start
                time.sleep(0.3)
        else:
            pytest.skip("serwer nie wystartował")
        yield base
    finally:
        kill_tree(process)


def fpv_state(page) -> dict:
    """Zmierz kamerę FPV względem drona (jednostki sceny = metry, bez THREE)."""
    return page.evaluate("""() => {
        const scene = window.__scene;
        const camera = scene.camera;
        const drone = scene.droneGroup;
        camera.updateMatrixWorld(true);
        drone.updateMatrixWorld(true);
        // macierz świata kamery (column-major): przesunięcie = [12..14]
        const m = camera.matrixWorld.elements;
        const cameraPos = [m[12], m[13], m[14]];
        // kamera patrzy wzdłuż własnego -Z; w świecie to -kolumna 3 macierzy
        const dir = [-m[8], -m[9], -m[10]];
        const length = Math.hypot(dir[0], dir[1], dir[2]) || 1;
        return {
            mode: scene.cameraMode,
            camera: cameraPos,
            drone: [drone.position.x, drone.position.y, drone.position.z],
            yaw: drone.rotation.y,
            dir: [dir[0] / length, dir[1] / length, dir[2] / length],
            attached: camera.parent === scene.fpvRig,
            rigParent: scene.fpvRig && scene.fpvRig.parent === scene.droneGroup,
            modelVisible: scene.droneScale.visible,
            rigLocal: [scene.fpvRig.position.x, scene.fpvRig.position.y,
                       scene.fpvRig.position.z],
        };
    }""")


def expected_camera(state: dict) -> list:
    """Oczekiwana pozycja kamery: dron + obrót(kurs) · przesunięcie obiektywu."""
    yaw = state["yaw"]
    dx = LENS_FORWARD_M * math.cos(yaw)
    dz = -LENS_FORWARD_M * math.sin(yaw)
    return [state["drone"][0] + dx, state["drone"][1] + LENS_HEIGHT_M,
            state["drone"][2] + dz]


def assert_fpv_attached(state: dict, moment: str) -> None:
    """Pozycja ±1 cm, kierunek ±1°, kamera przypięta, model ukryty."""
    assert state["mode"] == "fpv", moment
    assert state["attached"] is True, f"{moment}: kamera nie jest dzieckiem FPV rig"
    assert state["rigParent"] is True, f"{moment}: rig nie wisi na dronie"
    assert state["modelVisible"] is False, f"{moment}: model zasłania obiektyw"

    expected = expected_camera(state)
    error = math.dist(state["camera"], expected)
    assert error <= POSITION_TOLERANCE_M, (
        f"{moment}: kamera {state['camera']} != oczekiwana {expected} "
        f"(błąd {error * 100:.2f} cm)")

    yaw = state["yaw"]
    heading = math.atan2(-state["dir"][2], state["dir"][0])       # kurs z wektora
    diff = abs((heading - yaw + math.pi) % (2 * math.pi) - math.pi)
    assert math.degrees(diff) <= HEADING_TOLERANCE_DEG, (
        f"{moment}: kierunek {math.degrees(heading):.1f}° != kurs {math.degrees(yaw):.1f}°")
    assert abs(state["dir"][1]) <= 0.02, f"{moment}: kamera nie patrzy poziomo"


def open_flight(page, base: str, query: str = "") -> list:
    """Otwórz aplikację, włącz FPV i uruchom lot z zakrętami."""
    errors: list = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(base + query, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.__scene)", timeout=TIMEOUT_MS)
    page.wait_for_function("() => Boolean(window.__editor)", timeout=TIMEOUT_MS)
    page.evaluate("(src) => window.__editor.setValue(src)", FLIGHT)
    page.click("#btn-run")
    page.wait_for_function(
        "() => { const el = document.querySelector('#status-text');"
        "  return Boolean(el) && /Gotowe/.test(el.textContent); }",
        timeout=TIMEOUT_MS)
    page.wait_for_function("() => window.__scene.samples.length > 5",
                           timeout=TIMEOUT_MS)
    page.select_option("#camera-select", "fpv")
    page.wait_for_function("() => window.__scene.cameraMode === 'fpv'",
                           timeout=TIMEOUT_MS)
    return errors


def seek(page, ratio: float) -> None:
    page.evaluate("""(value) => {
        const scrub = document.querySelector('#scrub');
        scrub.value = String(value * Number(scrub.max));
        scrub.dispatchEvent(new Event('input', { bubbles: true }));
    }""", ratio)
    time.sleep(0.2)


@pytest.mark.parametrize("query", ["", "?lite=1"])
def test_fpv_camera_is_glued_to_drone(server, query):
    """Kamera = dron + obiektyw (±1 cm) i patrzy w kurs (±1°) w kilku chwilach lotu."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_flight(page, server, query)
        moments = {}
        for name, ratio in (("start", 0.0), ("wznoszenie", 0.15),
                            ("zakręt", 0.55), ("przelot", 0.75), ("lądowanie", 1.0)):
            seek(page, ratio)
            moments[name] = fpv_state(page)
        seek(page, 0.20)                       # przewinięcie wstecz
        moments["przewinięcie wstecz"] = fpv_state(page)
        sizes = {}
        for size in ("1", "3", "5", "10"):     # rozmiar nie rusza kamery
            page.select_option("#drone-size", size)
            time.sleep(0.15)
            sizes[size] = fpv_state(page)
        browser.close()
    assert errors == [], errors
    for name, state in moments.items():
        assert_fpv_attached(state, name)
    reference = sizes["1"]
    expected = expected_camera(reference)
    for size, state in sizes.items():
        assert_fpv_attached(state, f"rozmiar ×{size}")
        drift = math.dist(state["camera"], expected)
        assert drift <= 0.001, f"rozmiar ×{size}: kamera przesunięta o {drift * 100:.2f} cm"
    assert moments["start"]["rigLocal"] == pytest.approx(
        [LENS_FORWARD_M, LENS_HEIGHT_M, 0.0], abs=1e-9)


def test_fpv_camera_detaches_when_leaving_fpv(server):
    """Po powrocie z FPV kamera wraca do sceny, a model drona jest widoczny."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_flight(page, server)
        page.select_option("#camera-select", "orbit")
        page.wait_for_function("() => window.__scene.cameraMode === 'orbit'",
                               timeout=TIMEOUT_MS)
        time.sleep(0.3)
        state = page.evaluate("""() => {
            const scene = window.__scene;
            return {
                mode: scene.cameraMode,
                parent: scene.camera.parent === scene.scene ? 'scene' : 'dron',
                modelVisible: scene.droneScale.visible,
                fov: scene.camera.fov,
            };
        }""")
        browser.close()
    assert errors == [], errors
    assert state["mode"] == "orbit"
    assert state["parent"] == "scene", "kamera została przypięta do drona"
    assert state["modelVisible"] is True
    assert state["fov"] != 82.6


def test_fpv_camera_moves_during_turns(server):
    """Kamera obraca się razem z dronem (dwa różne kursy -> dwa różne kierunki)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_flight(page, server)
        headings = []
        for ratio in (0.1, 0.5, 0.62, 0.9):
            seek(page, ratio)
            state = fpv_state(page)
            assert_fpv_attached(state, f"kurs @ {ratio}")
            headings.append(round(math.degrees(state["yaw"]), 1))
        browser.close()
    assert errors == [], errors
    assert len(set(headings)) >= 2, f"lot nie zmienił kursu: {headings}"
