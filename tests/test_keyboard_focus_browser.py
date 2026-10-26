"""Testy przeglądarkowe: skróty klawiszowe nie przeszkadzają w pisaniu.

Sprawdzamy realny scenariusz z błędu: pisanie w edytorze kodu ze spacjami
i strzałkami. Spacja była globalnym skrótem play/pauza, a `document.activeElement`
w CodeMirror to `div[contenteditable]` - nie textarea - więc stary warunek
(``tagName in [TEXTAREA, INPUT, SELECT]``) jej nie łapał.

Testy pokrywają:

* edytor kodu (CodeMirror): tekst ze spacjami i strzałkami trafia do edytora,
  odtwarzanie nie startuje, dron nie rusza,
* pola liczbowe planera i edytora przeszkód,
* spacja przy aktywnym sterowaniu sceną -> play/pauza działa jak dotąd,
* lot ręczny: klawisze działają **tylko** po kliknięciu sceny 3D, Esc wyłącza.
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

#: minimalny lot do sprawdzenia play/pauzy (jak w teście FPV)
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
    """Serwer aplikacji na wolnym porcie (własna grupa procesów)."""
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


def open_app(page, server_url: str) -> list:
    """Otwórz aplikację i poczekaj na wtyczki + edytor."""
    errors: list = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.__editor)", timeout=TIMEOUT_MS)
    page.wait_for_function("() => Boolean(window.__featuresReady)", timeout=TIMEOUT_MS)
    return errors


def play_state(page) -> str:
    """Stan przycisku play: ``'⏸'`` = odtwarza, ``'▶'`` = pauza."""
    return page.inner_text("#btn-play").strip()


def pause_playback(page) -> None:
    """Ustaw pauzę (po uruchomieniu skryptu aplikacja odtwarza automatycznie)."""
    if play_state(page) == "⏸":
        page.click("#btn-play")
    page.wait_for_function(
        "() => document.querySelector('#btn-play').textContent.trim() === '▶'",
        timeout=TIMEOUT_MS)


def scrub_time(page) -> float:
    """Pozycja odtwarzania [s] z suwaka czasu."""
    return float(page.input_value("#scrub") or 0.0)


def open_script_tab(page) -> None:
    """Pokaż zakładkę Skrypt (po uruchomieniu aplikacja przełącza na Komendy)."""
    page.click("button[data-tab='tab-script']")
    page.locator(".cm-content").wait_for(state="visible", timeout=TIMEOUT_MS)


def run_mini_flight(page) -> None:
    """Uruchom krótki lot, żeby play/pauza miało co odtwarzać."""
    page.evaluate("(src) => window.__editor.setValue(src)", MINI_FLIGHT)
    page.click("#btn-run")
    page.wait_for_function(
        "() => { const el = document.querySelector('#status-text');"
        "  return Boolean(el) && /Gotowe/.test(el.textContent)"
        "    && window.__scene && window.__scene.samples.length > 5; }",
        timeout=TIMEOUT_MS)


# ------------------------------------------- pisanie w edytorze kodu
def test_typing_spaces_and_arrows_in_editor(server):
    """Spacje i strzałki w edytorze: tekst trafia do pola, odtwarzanie nie startuje."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        run_mini_flight(page)
        pause_playback(page)
        assert play_state(page) == "▶"
        time_before = scrub_time(page)

        page.evaluate("() => window.__editor.setValue('')")
        open_script_tab(page)
        page.click(".cm-content")
        page.keyboard.type("start lotu")
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowLeft")
        page.keyboard.type("X")
        text = page.evaluate("() => window.__editor.getValue()")
        state = play_state(page)
        time_after = scrub_time(page)
        browser.close()
    assert errors == [], errors
    assert text == "start loXtu", text        # spacja wpisana, strzałki przesunęły kursor
    assert state == "▶", "spacja w edytorze uruchomiła odtwarzanie"
    assert time_after == pytest.approx(time_before, abs=0.05)


def test_typing_in_editor_does_not_move_drone(server):
    """Litery W/A/S/D w edytorze nie sterują dronem (lot ręczny nieaktywny)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        page.click("#tab-btn-manual")
        page.locator("[data-mf-start]").click()
        page.wait_for_function(
            "() => window.__manualFlight.state.flying === true", timeout=TIMEOUT_MS)
        before = page.evaluate("() => window.__manualFlight.state.lastState")

        open_script_tab(page)
        page.click(".cm-content")               # fokus w edytorze
        page.keyboard.type("wasd ")
        page.wait_for_timeout(400)              # gdyby klawisze działały, dron by poleciał
        after = page.evaluate("() => window.__manualFlight.state.lastState")
        pressed = page.evaluate("() => window.__manualFlight.state.pressed")
        browser.close()
    assert errors == [], errors
    assert pressed == [], pressed
    assert after["x"] == pytest.approx(before["x"], abs=0.5)
    assert after["y"] == pytest.approx(before["y"], abs=0.5)


# ------------------------------------------- pola liczbowe (planer, przeszkody)
def test_space_in_planner_number_input(server):
    """Spacja/strzałki w polu liczbowym planera nie ruszają odtwarzania."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        run_mini_flight(page)
        pause_playback(page)
        page.locator("#tab-btn-route").click()
        speed = page.locator("#route-speed")
        speed.wait_for(state="visible", timeout=TIMEOUT_MS)
        speed.click()
        speed.fill("")
        speed.type("40")
        typed = speed.input_value()
        page.keyboard.press("Space")
        page.keyboard.press("ArrowUp")          # w polu type=number = +5 (step)
        value = speed.input_value()
        focused = page.evaluate("() => document.activeElement.id")
        state = play_state(page)
        browser.close()
    assert errors == [], errors
    assert typed == "40", typed                # cyfry trafiły do pola
    assert value == "45", value                # strzałka zmieniła POLE, nie odtwarzanie
    assert focused == "route-speed", focused   # fokus został w polu
    assert state == "▶", "skrót zadziałał mimo fokusu w polu liczbowym"


def test_space_in_obstacles_number_input(server):
    """To samo dla pola liczbowego w edytorze przeszkód."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        run_mini_flight(page)
        pause_playback(page)
        page.locator("#tab-btn-obstacles").click()
        # scena przykładowa z przeszkodami (test nie zakłada sceny domyślnej)
        page.locator(".obs-scene").first.click()
        item = page.locator("#obs-list .obs-item").first
        item.wait_for(state="visible", timeout=TIMEOUT_MS)
        item.click()
        field = page.locator("#tab-obstacles input[type=number]").first
        field.wait_for(state="visible", timeout=TIMEOUT_MS)
        field.click()
        page.keyboard.press("Space")
        page.keyboard.press("ArrowLeft")
        focused_in_input = page.evaluate(
            "() => Boolean(document.activeElement)"
            "  && document.activeElement.tagName === 'INPUT'")
        state = play_state(page)
        browser.close()
    assert errors == [], errors
    assert focused_in_input is True, "fokus wyszedł z pola liczbowego"
    assert state == "▶", "skrót zadziałał mimo fokusu w polu edytora przeszkód"


# ------------------------------------------- scena 3D: play/pauza i lot ręczny
def test_space_on_scene_toggles_playback(server):
    """Spacja przy fokusie na scenie 3D nadal włącza pauzę (jak dotąd)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        run_mini_flight(page)
        pause_playback(page)
        page.mouse.click(120, 120)              # klik w scenę (poza panelami)
        page.keyboard.press("Space")
        page.wait_for_function(
            "() => document.querySelector('#btn-play').textContent.trim() === '⏸'",
            timeout=TIMEOUT_MS)
        playing = play_state(page)
        page.keyboard.press("Space")
        page.wait_for_function(
            "() => document.querySelector('#btn-play').textContent.trim() === '▶'",
            timeout=TIMEOUT_MS)
        paused = play_state(page)
        browser.close()
    assert errors == [], errors
    assert playing == "⏸"
    assert paused == "▶"


def test_manual_flight_keys_require_scene_focus(server):
    """Sterowanie lotem ręcznym działa tylko po kliknięciu sceny; Esc je wyłącza."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = open_app(page, server)
        page.click("#tab-btn-manual")
        page.locator("[data-mf-start]").click()
        page.wait_for_function(
            "() => window.__manualFlight.state.flying === true", timeout=TIMEOUT_MS)
        badge = page.locator(".mf-control-badge")
        assert badge.is_hidden(), "plakietka widoczna bez kliknięcia sceny"
        start = page.evaluate("() => window.__manualFlight.state.lastState")

        # 1) bez kliknięcia sceny klawisze nie sterują
        page.keyboard.down("ArrowUp")
        page.wait_for_timeout(400)
        page.keyboard.up("ArrowUp")
        inactive = page.evaluate("() => window.__manualFlight.state.lastState")
        assert inactive["x"] == pytest.approx(start["x"], abs=0.6)

        # 2) kliknięcie sceny aktywuje sterowanie (widoczna plakietka)
        page.mouse.click(120, 120)
        badge.wait_for(state="visible", timeout=TIMEOUT_MS)
        assert page.evaluate("() => window.__manualFlight.state.controlActive") is True
        page.keyboard.down("ArrowUp")
        page.wait_for_function(
            "() => window.__manualFlight.state.lastState.x > 3",
            timeout=TIMEOUT_MS)
        page.keyboard.up("ArrowUp")
        moved = page.evaluate("() => window.__manualFlight.state.lastState")

        # 3) Esc wychodzi ze sterowania
        page.keyboard.press("Escape")
        badge.wait_for(state="hidden", timeout=TIMEOUT_MS)
        assert page.evaluate("() => window.__manualFlight.state.controlActive") is False
        page.keyboard.down("ArrowUp")
        page.wait_for_timeout(400)
        page.keyboard.up("ArrowUp")
        after_escape = page.evaluate("() => window.__manualFlight.state.lastState")
        browser.close()
    assert errors == [], errors
    assert moved["x"] > start["x"] + 3
    assert after_escape["x"] == pytest.approx(moved["x"], abs=0.6), (
        "po Esc dron nadal się ruszał")
