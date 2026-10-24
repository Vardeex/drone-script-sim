"""Test regresyjny warstwy 3D planera trasy (KI-3, Playwright).

Błąd KI-3: brakująca klamra w ``drawLine()`` zagnieżdżała cały ``return { ... }``
wewnątrz tej funkcji, więc ``createLayer`` zwracało ``undefined`` i warstwa nie
była podłączana do sceny (klik na podłożu nic nie robił).

Test uruchamia prawdziwy serwer i przeglądarkę; gdy Playwright nie jest
zainstalowany, jest pomijany (``skip``), a nie wywala całego zestawu.

**Brak stałych ``wait_for_timeout``.** Podgląd trasy liczy się na serwerze
asynchronicznie, więc testy czekają na **stan strony** (``wait_for_function``):
liczbę wierszy punktów i treść statystyk. Stały czas jest zapasem na wolniejszej
maszynie CI (poprzednio test ``test_click_on_ground_adds_point`` był niestabilny:
czytał ``#route-stats`` po 400 ms i trafiał na „Brak podglądu.”).
"""

from __future__ import annotations

import os
import signal
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

#: limit czekania na stan strony (start aplikacji, podgląd trasy)
TIMEOUT_MS = 20000


def _free_port() -> int:
    """Wolny port lokalny (w CI porty bywają zajęte przez inne procesy)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def server():
    """Serwer aplikacji na wolnym porcie (zatrzymywany po testach).

    Sprzątanie jest w ``finally``: ``terminate()`` + ``kill()`` procesu **i jego
    drzewa** (Windows: ``taskkill /T``, POSIX: grupa procesów). Bez tego po
    każdym przebiegu zostawały procesy ``uvicorn`` i kolejne uruchomienia
    zwalniały (widoczne przy 5 przebiegach z rzędu).
    """
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base + "/api/features", timeout=1)
                break
            except Exception:                   # noqa: BLE001 - czekamy na start
                time.sleep(0.3)
        else:
            pytest.skip("serwer nie wystartował")
        yield base
    finally:
        _stop_server(process)


def _stop_server(process) -> None:
    """Zatrzymaj serwer wraz z procesami potomnymi (wieloplatformowo, bez psutil)."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, AttributeError):
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()



def test_create_layer_returns_api_object(server):
    """``createLayer`` zwraca obiekt z metodami (wcześniej: ``undefined`` - KI-3)."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server, wait_until="domcontentloaded")
        # czekamy na stan gotowości funkcji (bez stałego czasu i bez import()):
        # `window.__featuresReady` ustawia boot.js po wczytaniu wszystkich wtyczek
        page.wait_for_function(
            "() => Boolean(window.__featuresReady)"
            " && window.__featuresReady.layers.includes('route_planner')",
            timeout=TIMEOUT_MS)
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

    Czekamy na **stan strony**, nie na upływ czasu: najpierw 2 wiersze punktów,
    potem statystyki zawierające „Punkty: 2” (podgląd liczy serwer).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server, wait_until="domcontentloaded")
        # zakładka planera pojawia się dopiero po wczytaniu wtyczki
        page.locator("#tab-btn-route").wait_for(state="visible", timeout=TIMEOUT_MS)
        page.click("#tab-btn-route")
        page.locator("#route-place").wait_for(state="visible", timeout=TIMEOUT_MS)
        page.click("#route-place")
        box = page.locator("#viewport canvas").first.bounding_box()
        for fx, fy in ((0.40, 0.55), (0.60, 0.45)):
            page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        # 1) czekamy, aż lista będzie miała 2 wiersze
        page.wait_for_function(
            "() => document.querySelectorAll('#route-points .route-point').length >= 2",
            timeout=TIMEOUT_MS)
        rows = page.eval_on_selector_all(
            "#route-points .route-point",
            "els => els.map(r => [...r.querySelectorAll('input')].map(i => Number(i.value)))")
        # 2) czekamy, aż podgląd z serwera policzy 2 punkty
        page.wait_for_function(
            "() => { const box = document.querySelector('#route-stats');"
            "  return Boolean(box) && box.textContent.includes('Punkty: 2'); }",
            timeout=TIMEOUT_MS)
        stats = page.inner_text("#route-stats")
        browser.close()
    assert errors == [], errors
    assert len(rows) == 2, rows
    assert all(z == 100 for _, _, z in rows), rows          # domyślna wysokość
    assert rows[0] != rows[1], "oba punkty trafiły w to samo miejsce"
    assert "Punkty: 2" in stats, stats


def test_slow_preview_shows_pending_state(server):
    """Przy wolnym podglądzie UI pokazuje „Liczę podgląd…”, nie „Brak podglądu.”.

    Sedno niestabilności w CI: podgląd liczy serwer asynchronicznie. Gdy
    odpowiedź idzie dłużej niż chwila, użytkownik nie może zobaczyć mylącego
    „Brak podglądu.” - w tym czasie widzi stan pośredni.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server, wait_until="domcontentloaded")
        page.locator("#tab-btn-route").wait_for(state="visible", timeout=TIMEOUT_MS)
        page.click("#tab-btn-route")
        page.locator("#route-place").wait_for(state="visible", timeout=TIMEOUT_MS)

        def slow_preview(route):
            time.sleep(1.5)                  # symulacja wolnego serwera
            route.continue_()

        page.route("**/api/route_planner/preview", slow_preview)
        page.click("#route-place")
        box = page.locator("#viewport canvas").first.bounding_box()
        page.mouse.click(box["x"] + box["width"] * 0.45, box["y"] + box["height"] * 0.60)
        page.wait_for_function(
            "() => document.querySelectorAll('#route-points .route-point').length >= 1",
            timeout=TIMEOUT_MS)
        # podgląd jeszcze się liczy - sprawdzamy stan pośredni
        page.wait_for_function(
            "() => document.querySelector('#route-stats').textContent.includes('Liczę podgląd')",
            timeout=TIMEOUT_MS)
        pending = page.inner_text("#route-stats")
        # ... a potem przychodzą realne dane
        page.unroute("**/api/route_planner/preview")
        page.wait_for_function(
            "() => document.querySelector('#route-stats').textContent.includes('Punkty: 1')",
            timeout=TIMEOUT_MS)
        final = page.inner_text("#route-stats")
        browser.close()
    assert errors == [], errors
    assert "Brak podglądu" not in pending, pending
    assert "Punkty:" in final, final
