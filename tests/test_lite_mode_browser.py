"""Testy przeglądarkowe trybu lekkiego („słaby komputer”).

Sprawdzają, że tryb lekki:

* włącza się parametrem adresu ``?lite=1`` **oraz** ustawieniem zapamiętanym
  w select ``#perf-mode`` / ``localStorage``,
* faktycznie zmienia scenę (brak cieni, pixelRatio 1, prostszy model drona,
  brak etykiet-sprite'ów, uproszczona trasa) i nie wywala błędów konsoli,
* rysuje na żądanie (w bezczynności liczba klatek rysowanych jest mała),
* nie zabiera funkcji: edytor, uruchamianie, odtwarzanie, tabela komend.

``DRONESIM_TEST_LITE=1`` (patrz ``conftest.py``) uruchamia **cały** zestaw
przeglądarkowy w trybie lekkim - testy parametryzowane są na poziomie zestawu.
"""

from __future__ import annotations

import os
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

MINI_FLIGHT = """from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.move_forward(100)
tello.rotate_clockwise(90)
tello.move_forward(100)
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


@pytest.fixture(scope="module")
def potatoes_server(tmp_path_factory):
    """Serwer udający edycję ``for_potatoes`` (plik ``edition.json``)."""
    folder = tmp_path_factory.mktemp("edition")
    edition_file = folder / "edition.json"
    edition_file.write_text('{"edition": "for_potatoes"}', encoding="utf-8")
    port = _free_port()
    env = dict(os.environ, DRONESIM_EDITION_FILE=str(edition_file))
    process = spawn(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
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


def test_potatoes_edition_starts_in_lite_mode(potatoes_server):
    """Edycja for_potatoes: tryb lekki od startu, plakietka i tytuł z edycją."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_app(page, potatoes_server)      # bez ?lite=1!
        state = scene_state(page)
        edition_info = page.evaluate("""async () => {
            const data = await (await fetch('/api/edition')).json();
            return data;
        }""")
        badge = page.locator("#edition-badge")
        badge_text = badge.text_content() if badge.is_visible() else ""
        title = page.title()
        footer = page.text_content("#footer-edition") or ""
        select = page.input_value("#perf-mode")
        fpv_disabled = page.evaluate(
            "() => document.querySelector('#camera-select option[value=\\'fpv\\']').disabled")
        browser.close()
    assert errors == [], errors
    assert state["lite"] is True, "edycja for_potatoes ma startować w trybie lekkim"
    assert edition_info["edition"] == "for_potatoes"
    assert edition_info["lite_default"] is True
    assert badge_text.strip() == "for_potatoes", badge_text
    assert "for_potatoes" in title, title
    assert "for_potatoes" in footer, footer
    assert select == "lite"
    assert fpv_disabled is True


def open_app(page, server_url: str, query: str = "") -> list:
    """Otwórz aplikację (opcjonalnie z parametrem adresu) i poczekaj na start."""
    errors: list = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(server_url + query, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.__scene)", timeout=TIMEOUT_MS)
    page.wait_for_function("() => Boolean(window.__featuresReady)", timeout=TIMEOUT_MS)
    page.wait_for_function("() => Boolean(window.__editor)", timeout=TIMEOUT_MS)
    return errors


def scene_state(page) -> dict:
    """Stan sceny istotny dla trybu lekkiego."""
    return page.evaluate("""() => {
        const scene = window.__scene;
        return {
            lite: Boolean(scene.lite),
            shadows: Boolean(scene.renderer.shadowMap.enabled),
            pixelRatio: scene.renderer.getPixelRatio(),
            scale: scene.renderScale,
            fineGrid: Boolean(scene._fineGrid && scene._fineGrid.visible),
            spriteLabels: (scene.markerGroup ? scene.markerGroup.children : [])
                .filter((child) => child.isSprite).length,
        };
    }""")


@pytest.mark.parametrize("query", ["?lite=1", "?lite=1&x=1"])
def test_lite_mode_from_url(server, query):
    """``?lite=1`` włącza tryb lekki bez pytania i bez zapisu ustawienia."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_app(page, server, query)
        state = scene_state(page)
        body_class = page.evaluate("() => document.body.classList.contains('lite-mode')")
        select = page.input_value("#perf-mode")
        stored = page.evaluate("() => localStorage.getItem('dronesim.perf')")
        browser.close()
    assert errors == [], errors
    assert state["lite"] is True
    assert body_class is True
    assert select == "lite"
    assert stored is None, "?lite=1 nie powinien zapisywać ustawienia"
    assert state["shadows"] is False
    assert state["pixelRatio"] == 1


def test_lite_mode_from_settings_and_persisted(server):
    """Wybór „Lekka” w select włącza tryb lekki i jest pamiętany po odświeżeniu."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()
        errors = open_app(page, server)
        before = scene_state(page)
        page.select_option("#perf-mode", "lite")
        page.wait_for_function("() => Boolean(window.__scene.lite)", timeout=TIMEOUT_MS)
        state = scene_state(page)
        stored = page.evaluate("() => localStorage.getItem('dronesim.perf')")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__scene)", timeout=TIMEOUT_MS)
        page.wait_for_function("() => Boolean(window.__scene.lite)", timeout=TIMEOUT_MS)
        after_reload = scene_state(page)
        browser.close()
    assert errors == [], errors
    assert before["lite"] is False
    assert state["lite"] is True and state["shadows"] is False
    assert stored == "lite", stored
    assert after_reload["lite"] is True


def test_lite_simplifies_scene_but_keeps_features(server):
    """Tryb lekki: prostszy dron, brak sprite'ów, trasa uproszczona - funkcje działają."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        errors = open_app(page, server, "?lite=1")
        page.evaluate("(src) => window.__editor.setValue(src)", MINI_FLIGHT)
        page.click("#btn-run")
        page.wait_for_function(
            "() => { const el = document.querySelector('#status-text');"
            "  return Boolean(el) && /Gotowe/.test(el.textContent); }",
            timeout=TIMEOUT_MS)
        page.wait_for_function("() => window.__scene.samples.length > 5",
                               timeout=TIMEOUT_MS)
        info = page.evaluate("""() => {
            const scene = window.__scene;
            const lines = (scene.trailGroup.children || []).filter(
                (child) => child.isLine);
            const positions = lines.length
                ? lines[0].geometry.attributes.position.count : 0;
            return {
                samples: scene.samples.length,
                trailPositions: positions,
                spriteLabels: (scene.markerGroup.children || [])
                    .filter((child) => child.isSprite).length,
                droneName: scene.drone ? scene.drone.name : null,
                rotorAnimated: Boolean(scene.engines && scene.engines.length),
                commands: document.querySelectorAll('#commands-table tbody tr').length,
            };
        }""")
        page.evaluate("""() => {
            const scrub = document.querySelector('#scrub');
            scrub.value = String(Number(scrub.max) / 2);
            scrub.dispatchEvent(new Event('input', { bubbles: true }));
        }""")
        scrub_value = float(page.input_value("#scrub"))
        hud_time = page.inner_text("#hud-time")
        time.sleep(0.3)
        browser.close()
    assert errors == [], errors
    assert info["droneName"] == "tello-lite", info
    assert info["rotorAnimated"] is False, "uproszczony model nie animuje śmigieł"
    assert info["spriteLabels"] == 0, info
    assert info["trailPositions"] <= info["samples"], info
    assert info["commands"] > 3, "tabela komend nadal działa"
    assert scrub_value > 0.5
    assert hud_time.strip() not in ("", "0.00 s"), hud_time


def test_lite_renders_on_demand(server):
    """W bezczynności tryb lekki rysuje znacznie mniej klatek niż pełny."""
    def frames_for(query: str) -> int:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            errors = open_app(page, server, query)
            assert errors == [], errors
            before = page.evaluate("() => window.__scene.renderer.info.render.frame")
            time.sleep(1.5)
            after = page.evaluate("() => window.__scene.renderer.info.render.frame")
            browser.close()
        return int(after) - int(before)

    full = frames_for("")
    lite = frames_for("?lite=1")
    assert lite <= 6, f"tryb lekki narysował {lite} klatek bez zmian (oczekiwane <= 6)"
    assert full > lite, (full, lite)

