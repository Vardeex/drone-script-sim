"""Testy przeglądarkowe: pusta scena na start i zapamiętywanie wybranej sceny.

Wymagania (zadanie 2):

* pierwsze uruchomienie i „✚ Nowa” dają **pustą** scenę roboczą (tylko podłoże,
  osie i punkt startu) - bez bramek ani przeszkód,
* ostatnio wybrana scena jest pamiętana w ``localStorage`` i wracamy do niej
  po odświeżeniu,
* sceny przykładowe (slalom, tor przeszkód, pokój, maty) są nadal na liście.

Każdy test otwiera **świeży kontekst** przeglądarki, więc ``localStorage`` jest
pusty i „pierwsze uruchomienie” jest naprawdę pierwszym.
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

#: klucz w localStorage z ostatnio wybraną sceną (patrz obstacles/panel.js)
SCENE_KEY = "dronesim.obstacles.scene"


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


def open_obstacles(page, server_url: str) -> list:
    """Otwórz aplikację i zakładkę Przeszkody; zwróć błędy strony."""
    errors: list = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.__featuresReady)", timeout=TIMEOUT_MS)
    page.locator("#tab-btn-obstacles").wait_for(state="visible", timeout=TIMEOUT_MS)
    page.click("#tab-btn-obstacles")
    return errors


def element_text(page, selector: str) -> str:
    """Źródłowy tekst elementu (CSS może go zmieniać na wielkie litery)."""
    return (page.text_content(selector) or "").strip()


def wait_empty_scene(page) -> None:
    """Poczekaj, aż panel pokaże pustą scenę roboczą."""
    page.wait_for_function(
        "() => { const list = document.querySelector('#obs-list');"
        "  return Boolean(list) && list.textContent.includes('pusta'); }",
        timeout=TIMEOUT_MS)


def wait_scene_loaded(page, title: str) -> None:
    """Poczekaj, aż wczytana będzie scena o podanej nazwie."""
    page.wait_for_function(
        "([expected]) => { const t = document.querySelector('#obs-title');"
        "  return Boolean(t) && t.textContent.trim() === expected; }",
        arg=[title], timeout=TIMEOUT_MS)


def test_first_run_is_empty_workspace_scene(server):
    """Pierwsze uruchomienie: pusta scena (bez bramek), sceny przykładowe na liście."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1600, "height": 950})
        page = context.new_page()
        errors = open_obstacles(page, server)
        wait_empty_scene(page)
        items = page.locator("#obs-list .obs-item").count()
        title = element_text(page, "#obs-title")
        path = element_text(page, "#obs-path")
        stored = page.evaluate(f"() => localStorage.getItem('{SCENE_KEY}')")
        examples = page.locator(".obs-scene").count()
        browser.close()
    assert errors == [], errors
    assert items == 0, f"scena nie jest pusta: {items} przeszkód"
    assert title == "Nowa scena", title
    assert path == "scena robocza", path
    assert stored is None, f"pierwsze uruchomienie nie powinno pamiętać sceny: {stored}"
    assert examples >= 4, f"na liście jest tylko {examples} scen"


def test_selected_scene_is_remembered(server):
    """Wybrana scena jest zapamiętana i wraca po odświeżeniu strony."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1600, "height": 950})
        page = context.new_page()
        errors = open_obstacles(page, server)
        wait_empty_scene(page)

        page.locator(".obs-scene").first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#obs-list .obs-item').length > 0",
            timeout=TIMEOUT_MS)
        title = element_text(page, "#obs-title")
        obstacles = page.locator("#obs-list .obs-item").count()
        stored = page.evaluate(f"() => localStorage.getItem('{SCENE_KEY}')")

        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__featuresReady)",
                               timeout=TIMEOUT_MS)
        wait_scene_loaded(page, title)
        page.wait_for_function(
            "([count]) => document.querySelectorAll('#obs-list .obs-item').length"
            " === count", arg=[obstacles], timeout=TIMEOUT_MS)
        title_after_reload = element_text(page, "#obs-title")
        restored = page.locator("#obs-list .obs-item").count()
        browser.close()
    assert errors == [], errors
    # w localStorage trzymamy nazwę pliku sceny (np. ``gate_slalom``), a tytuł
    # w UI to nazwa wyświetlana („Slalom z bramkami”) - sprawdzamy oba skutki
    assert stored, "scena nie została zapamiętana w localStorage"
    assert restored == obstacles, (restored, obstacles)
    assert title_after_reload == title, (title_after_reload, title)


def test_new_scene_clears_remembered_scene(server):
    """„✚ Nowa” daje pustą scenę i nie wraca do poprzedniej po odświeżeniu."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1600, "height": 950})
        page = context.new_page()
        errors = open_obstacles(page, server)
        wait_empty_scene(page)
        page.locator(".obs-scene").first.click()          # najpierw wybierz scenę
        page.wait_for_function(
            "() => document.querySelectorAll('#obs-list .obs-item').length > 0",
            timeout=TIMEOUT_MS)

        page.click("#obs-new")                            # potem „Nowa”
        wait_empty_scene(page)
        cleared = page.evaluate(f"() => localStorage.getItem('{SCENE_KEY}')")

        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__featuresReady)",
                               timeout=TIMEOUT_MS)
        wait_empty_scene(page)
        items = page.locator("#obs-list .obs-item").count()
        browser.close()
    assert errors == [], errors
    assert cleared is None, cleared
    assert items == 0, f"po „Nowa” i odświeżeniu jest {items} przeszkód"
