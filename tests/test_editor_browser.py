"""Test przeglądarkowy edytora: CodeMirror 6, podpowiedzi po ``tello.``, ostrzeżenia.

Sprawdzamy to, co użytkownik naprawdę widzi:

* edytor się ładuje (``.cm-editor``), ma numery linii, a ukryta textarea
  pozostaje źródłem wartości dla reszty aplikacji,
* po wpisaniu ``tello.`` pojawia się podpowiedź z metodami mocka,
* ``move_forward(600)`` daje ostrzeżenie **z numerem linii** i podkreśla linię.
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


def _open_editor(page, server_url: str) -> list:
    errors: list = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.__editor)", timeout=TIMEOUT_MS)
    page.locator(".cm-editor").wait_for(state="visible", timeout=TIMEOUT_MS)
    return errors


def test_editor_loads_with_line_numbers(server):
    """Edytor to CodeMirror 6 z numerami linii; textarea jest ukryta, ale wciąż działa."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = _open_editor(page, server)
        gutters = page.locator(".cm-lineNumbers").count()
        hidden = page.evaluate(
            "() => { const t = document.querySelector('#editor-area');"
            "  return { hidden: t.classList.contains('editor-source-hidden'),"
            "           display: getComputedStyle(t).display }; }")
        # wartość wpisana w edytor trafia do ukrytej textarea (zgodność ze starym kodem)
        page.evaluate("() => window.__editor.setValue('tello.takeoff()')")
        value = page.input_value("#editor-area")
        browser.close()
    assert errors == [], errors
    assert gutters >= 1, "brak numerów linii"
    assert hidden["display"] == "none", hidden
    assert value == "tello.takeoff()"


def test_suggestion_appears_after_dot(server):
    """Po wpisaniu ``tello.`` pojawia się podpowiedź z metodami mocka Tello."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = _open_editor(page, server)
        page.click(".cm-content")
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.keyboard.type("tello = Tello()\ntello.")
        page.locator(".cm-tooltip-autocomplete").wait_for(
            state="visible", timeout=TIMEOUT_MS)
        labels = page.locator(".cm-tooltip-autocomplete li").all_inner_texts()
        browser.close()
    assert errors == [], errors
    joined = " ".join(labels)
    assert "move_forward" in joined, labels[:10]
    assert "takeoff" in joined, labels[:10]


def test_warning_for_out_of_range_move(server):
    """``move_forward(600)`` daje ostrzeżenie z linią i podkreślenie w edytorze."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = _open_editor(page, server)
        page.evaluate("""() => window.__editor.setValue(
          'tello = Tello()\\ntello.takeoff()\\ntello.move_forward(600)\\ntello.land()')""")
        page.wait_for_function(
            "() => (window.__scriptProblems || []).length > 0",
            timeout=TIMEOUT_MS)
        problems = page.evaluate("() => window.__scriptProblems")
        text = page.inner_text("#script-problems")
        marked = page.locator(".cm-warning-line").count()
        browser.close()
    assert errors == [], errors
    assert len(problems) == 1, problems
    assert problems[0]["line"] == 3, problems
    assert "600" in problems[0]["message"]
    assert "linia 3" in text, text
    assert marked >= 1, "linia z ostrzeżeniem nie jest podkreślona"
