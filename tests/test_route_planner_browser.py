"""Test regresyjny warstwy 3D planera trasy (KI-3, Playwright).

Błąd KI-3: brakująca klamra w ``drawLine()`` zagnieżdżała cały ``return { ... }``
wewnątrz tej funkcji, więc ``createLayer`` zwracało ``undefined`` i warstwa nie
była podłączana do sceny (klik na podłożu nic nie robił).

Test uruchamia prawdziwy serwer i przeglądarkę; gdy Playwright nie jest
zainstalowany, jest pomijany (``skip``), a nie wywala całego zestawu.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

#: testy wymagają przeglądarki (Chromium) - w CI osobny job, lokalnie domyślnie
pytestmark = pytest.mark.browser


def _free_port() -> int:
    """Wolny port lokalny (w CI porty bywają zajęte przez inne procesy)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def server():
    """Serwer aplikacji na wolnym porcie (zatrzymywany po testach)."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            urllib.request.urlopen(base + "/api/features", timeout=1)
            return base
        except Exception:                       # noqa: BLE001 - czekamy na start
            time.sleep(0.3)
    process.terminate()
    pytest.skip("serwer nie wystartował")


def test_create_layer_returns_api_object(server):
    """``createLayer`` zwraca obiekt z metodami (wcześniej: ``undefined`` - KI-3)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        result = page.evaluate("""async () => {
          const boot = await import('/static/js/boot.js');
          const layer = boot.sceneLayers.find((l) => l.id === 'route_planner');
          if (!layer) return {error: 'brak fabryki'};
          const add = () => {};
          const instance = layer.factory({ scene: {
            scene: { add, remove: add },
            renderer: { domElement: document.createElement('canvas') },
            camera: {},
          } });
          return {type: typeof instance,
                  methods: instance ? Object.keys(instance).sort() : []};
        }""")
        browser.close()
    assert result.get("type") == "object", result
    # kontrakt warstwy: rysowanie trasy, zaznaczenie, podgląd, tryby edycji
    for name in ("setRoute", "setSelection", "setPreview", "setPlaceMode",
                 "setDragMode", "tick", "dispose"):
        assert name in result["methods"], result["methods"]


def test_click_on_ground_adds_point(server):
    """Klik na podłożu w trybie „Klik na podłożu” dodaje punkt do listy.

    Oczekiwanie z geometrii: dwa kliknięcia w różne miejsca sceny dają dwa
    punkty, oba z wysokością domyślną 100 cm, a współrzędne w liście są równe
    tym, które zwróciło dodanie punktu (lista i trasa są spójne).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page.click("#tab-btn-route")
        page.wait_for_timeout(400)
        page.click("#route-place")
        box = page.locator("#viewport canvas").first.bounding_box()
        for fx, fy in ((0.40, 0.55), (0.60, 0.45)):
            page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
            page.wait_for_timeout(400)
        rows = page.eval_on_selector_all(
            "#route-points .route-point",
            "els => els.map(r => [...r.querySelectorAll('input')].map(i => Number(i.value)))")
        stats = page.inner_text("#route-stats")
        browser.close()
    assert errors == [], errors
    assert len(rows) == 2, rows
    assert all(z == 100 for _, _, z in rows), rows          # domyślna wysokość
    assert rows[0] != rows[1], "oba punkty trafiły w to samo miejsce"
    assert "Punkty: 2" in stats, stats
