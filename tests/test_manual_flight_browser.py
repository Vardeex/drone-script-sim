"""Test przeglądarkowy „Lotu ręcznego”: klawisze ruszają drona we właściwą stronę.

Sprawdzamy **trzy** rzeczy naraz (wszystkie z geometrii, nie z wyniku programu):

1. ``ArrowUp`` przesuwa drona do przodu - w układzie projektu ``x`` rośnie,
2. ``ArrowRight`` przesuwa go w prawo - w układzie projektu ``y`` **maleje**
   (oś ``y`` wskazuje lewo), a w scenie three.js ``z`` rośnie,
3. przy kamerze śledzącej **z tyłu drona** rzut pozycji drona na ekran
   (NDC ``x``) rośnie - czyli „prawo" drona to prawo ekranu.

Dodatkowo: brak błędów w konsoli i generowanie skryptu w obu wariantach.
"""

from __future__ import annotations

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

#: komendy RC wysyłane są co tyle milisekund - test czeka na efekt, nie na czas
TICK_S = 0.1


@pytest.fixture(scope="module")
def server():
    """Serwer aplikacji na wolnym porcie (własna grupa procesów, jak w innych testach)."""
    port = _free_port()
    process = spawn(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/features", timeout=1)
                break
            except Exception:                       # noqa: BLE001 - czekamy na start
                time.sleep(0.3)
        else:
            pytest.skip("serwer nie wystartował")
        yield base
    finally:
        kill_tree(process)


def _open_panel(page, server_url: str) -> None:
    """Otwórz zakładkę „Lot ręczny” i ustaw kamerę śledzącą."""
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_function(
        "() => Boolean(window.__featuresReady)"
        " && window.__featuresReady.layers.includes('manual_flight')",
        timeout=TIMEOUT_MS)
    page.locator("#tab-btn-manual").wait_for(state="visible", timeout=TIMEOUT_MS)
    page.click("#tab-btn-manual")
    page.locator("[data-mf-start]").wait_for(state="visible", timeout=TIMEOUT_MS)
    page.select_option("#camera-select", "follow")
    page.wait_for_function(
        "() => window.__scene && window.__scene.cameraMode === 'follow'",
        timeout=TIMEOUT_MS)


def _start_flight(page) -> None:
    page.click("[data-mf-start]")
    page.wait_for_function(
        "() => window.__manualFlight && window.__manualFlight.state.flying === true",
        timeout=TIMEOUT_MS)


def _drone_position(page):
    return page.evaluate(
        "() => { const p = window.__scene.droneGroup.position;"
        "  return { x: p.x, y: p.y, z: p.z }; }")


def _hold(page, key: str, seconds: float = 0.7) -> None:
    """Przytrzymaj klawisz (prawdziwe zdarzenia klawiatury) i puść."""
    page.keyboard.down(key)
    page.wait_for_timeout(int(seconds * 1000))
    page.keyboard.up(key)


def test_arrow_up_moves_drone_forward(server):
    """``ArrowUp`` = przód: w układzie projektu rośnie ``x``."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        _open_panel(page, server)
        _start_flight(page)
        before = page.evaluate("() => window.__manualFlight.state.lastState")
        _hold(page, "ArrowUp")
        page.wait_for_function(
            "() => { const s = window.__manualFlight.state.lastState;"
            "  return s && s.x > 5; }",
            timeout=TIMEOUT_MS)
        after = page.evaluate("() => window.__manualFlight.state.lastState")
        browser.close()
    assert errors == [], errors
    assert before["x"] == pytest.approx(0.0, abs=0.5)
    assert after["x"] > 5.0, after          # przy 50 cm/s w 0,7 s ~17 cm
    assert abs(after["y"]) < 3.0, after     # przód nie skręca


def test_arrow_right_moves_drone_right_on_screen(server):
    """``ArrowRight`` = prawo drona = prawo ekranu przy kamerze z tyłu.

    Kamera pościgowa trzyma drona blisko środka ekranu, więc nie sprawdzamy
    rzutu samego drona (jest ~0), ale **kierunek przemieszczenia względem osi
    „prawo" kamery**: iloczyn skalarny przemieszczenia i wektora ``right``
    kamery (z ``matrixWorld``) musi być dodatni.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        _open_panel(page, server)
        _start_flight(page)
        page.wait_for_function(
            "() => { const s = window.__scene;"
            "  return s && s.cameraMode === 'follow' && Boolean(s._lastSample); }",
            timeout=TIMEOUT_MS)
        page.wait_for_timeout(700)          # kamera ustawia się za dronem
        before = _drone_position(page)

        _hold(page, "ArrowRight")
        page.wait_for_function(
            "() => { const s = window.__manualFlight.state.lastState;"
            "  return s && s.y < -5; }",
            timeout=TIMEOUT_MS)
        state = page.evaluate("() => window.__manualFlight.state.lastState")
        after = _drone_position(page)
        screen_right = page.evaluate(
            "() => { const m = window.__scene.camera.matrixWorld.elements;"
            "  return { x: m[0], y: m[1], z: m[2] }; }")
        browser.close()
    assert errors == [], errors
    # 1) serwer: prawo = malejące y (oś y wskazuje lewo)
    assert state["y"] < -5.0, state
    # 2) scena: z = -y, więc z rośnie (dron jedzie w stronę +z sceny)
    assert after["z"] > before["z"] + 0.03, (before, after)
    # 3) ekran: przemieszczenie ma dodatni rzut na wektor „prawo" kamery
    delta = {axis: after[axis] - before[axis] for axis in ("x", "y", "z")}
    projection = (delta["x"] * screen_right["x"] + delta["y"] * screen_right["y"]
                  + delta["z"] * screen_right["z"])
    assert projection > 0.02, (delta, screen_right, projection)


def test_record_and_generate_script(server):
    """Nagranie z UI generuje skrypt (wariant wierny i uproszczony)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        _open_panel(page, server)
        # prędkość 100, żeby ruchy przekroczyły limit 20 cm wariantu uproszczonego
        page.evaluate("""() => {
          const slider = document.querySelector('[data-mf-speed]');
          slider.value = '100';
          slider.dispatchEvent(new Event('input', {bubbles: true}));
        }""")
        _start_flight(page)
        _hold(page, "ArrowUp", 0.8)        # 50 cm/s * 0,8 s = 40 cm
        _hold(page, "d", 0.5)              # obrót w prawo 45°
        _hold(page, "ArrowUp", 0.8)
        page.click("[data-mf-land]")
        page.wait_for_function(
            "() => window.__manualFlight.state.flying === false",
            timeout=TIMEOUT_MS)

        page.click("[data-mf-script]")
        page.wait_for_function(
            "() => { const pre = document.querySelector('[data-mf-script-out]');"
            "  return pre && !pre.hidden && pre.textContent.includes('Tello'); }",
            timeout=TIMEOUT_MS)
        faithful = page.inner_text("[data-mf-script-out]")
        assert "tello.send_rc_control" in faithful

        page.select_option("[data-mf-variant]", "simple")
        page.click("[data-mf-script]")
        page.wait_for_function(
            "() => document.querySelector('[data-mf-script-out]')"
            "  .textContent.includes('move_forward')",
            timeout=TIMEOUT_MS)
        simple = page.inner_text("[data-mf-script-out]")
        assert "tello.send_rc_control" not in simple      # inny wariant
        assert "tello.move_forward" in simple
        assert "rotate_clockwise" in simple      # obrót z nagrania (klawisz D)
        browser.close()
    assert errors == [], errors
