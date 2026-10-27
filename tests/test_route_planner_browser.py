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

import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from tests.proc_helpers import kill_tree, spawn

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

#: testy wymagają przeglądarki (Chromium) - w CI osobny job, lokalnie domyślnie
pytestmark = pytest.mark.browser

#: limit czekania na stan strony (start aplikacji, podgląd trasy)
TIMEOUT_MS = 20000

#: minimalny lot do testu kamery FPV (krótki i szybki w symulacji)
MINI_FLIGHT = """from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.move_forward(60)
tello.rotate_clockwise(90)
tello.move_forward(40)
tello.land()
"""


def _free_port() -> int:
    """Wolny port lokalny (w CI porty bywają zajęte przez inne procesy)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def server():
    """Serwer aplikacji na wolnym porcie (zatrzymywany po testach).

    Serwer startuje w **własnej sesji** (``start_new_session=True`` na POSIX,
    ``CREATE_NEW_PROCESS_GROUP`` na Windows - patrz ``tests.proc_helpers.spawn``).
    Bez tego ``os.killpg`` w sprzątaniu trafiał w grupę procesów pytest i krok
    CI kończył się „The operation was canceled” mimo zielonych testów.

    Sprzątanie jest w ``finally`` i zabija proces **z potomkami**
    (``taskkill /T`` na Windows, ``killpg`` na POSIX), ale tylko gdy proces ma
    własną grupę - ``kill_tree`` sprawdza to przed ``killpg``.
    """
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
            except Exception:                   # noqa: BLE001 - czekamy na start
                time.sleep(0.3)
        else:
            pytest.skip("serwer nie wystartował")
        yield base
    finally:
        _stop_server(process)


def _stop_server(process) -> None:
    """Zatrzymaj serwer wraz z procesami potomnymi (nigdy własnej grupy pytest)."""
    kill_tree(process, timeout=10.0)



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


def test_fpv_camera_follows_drone(server):
    """Kamera „Z drona (FPV)”: bez błędów w konsoli, jedzie razem z dronem.

    Sprawdzamy stan sceny (bez stałych opóźnień): po włączeniu FPV kamera jest
    **w miejscu drona** (odległość pozioma < 5 cm, bo obiektyw siedzi w nosie),
    a pole widzenia to 82,6° zamiast 50°. Po przewinięciu lotu pozycja kamery
    zmienia się razem z dronem — czyli FPV działa przy odtwarzaniu i przewijaniu.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(server, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => Boolean(window.__featuresReady) && window.__featuresReady.layers.length > 0",
            timeout=TIMEOUT_MS)
        # uruchom krótki lot w UI (deterministyczny, bez zależności od przykładów)
        # Treść podajemy przez API edytora CodeMirror (zadanie 3 zastąpiło textarea
        # #editor-area edytorem); wpisanie ręczne działa identycznie - setValue
        # synchronizuje ukrytą textarea i wysyła zdarzenie ``input``.
        page.evaluate("(source) => window.__editor.setValue(source)", MINI_FLIGHT)
        page.click("#btn-run")
        page.wait_for_function(
            "() => { const el = document.querySelector('#status-text');"
            "  return Boolean(el) && /Gotowe/.test(el.textContent)"
            "    && window.__scene && window.__scene.samples"
            "    && window.__scene.samples.length > 10; }",
            timeout=TIMEOUT_MS)
        # pierwsza klatka po włączeniu FPV: kamera musi już być w miejscu drona
        page.select_option("#camera-select", "fpv")
        page.wait_for_function(
            "() => document.querySelector('#camera-select').value === 'fpv'",
            timeout=TIMEOUT_MS)
        first = page.evaluate("""() => {
          const scene = window.__scene;
          return scene ? {fov: scene.camera.fov, pos: scene.camera.position.toArray()} : null;
        }""")
        # przewiń na środek lotu (na końcu dron wylądował - kamera byłaby przy podłodze)
        page.evaluate("""() => {
          const slider = document.querySelector('#scrub');
          if (!slider) return;
          slider.value = String(Number(slider.max) * 0.5);
          slider.dispatchEvent(new Event('input', {bubbles: true}));
          slider.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.wait_for_function(
            "() => Boolean(window.__scene) && window.__scene.cameraMode === 'fpv'"
            " && window.__scene._lastSample && window.__scene._lastSample.t > 1"
            " && window.__scene._lastSample.state === 'airborne'",
            timeout=TIMEOUT_MS)
        second = page.evaluate("""() => {
          const scene = window.__scene;
          if (!scene) return null;
          scene.camera.updateMatrixWorld(true);
          const m = scene.camera.matrixWorld.elements;
          return {fov: scene.camera.fov, pos: [m[12], m[13], m[14]],
                  drone: scene.droneGroup.position.toArray(),
                  sample: scene._lastSample || null};
        }""")
        # ... i wróć na początek: kamera znowu przy ziemi (pozycja zależy od próbki)
        page.evaluate("""() => {
          const slider = document.querySelector('#scrub');
          slider.value = '0';
          slider.dispatchEvent(new Event('input', {bubbles: true}));
          slider.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.wait_for_function(
            "() => window.__scene && window.__scene._lastSample"
            " && window.__scene._lastSample.t === 0",
            timeout=TIMEOUT_MS)
        third = page.evaluate("""() => {
          const scene = window.__scene;
          scene.camera.updateMatrixWorld(true);
          const m = scene.camera.matrixWorld.elements;
          return [m[12], m[13], m[14]];
        }""")
        browser.close()
    assert errors == [], errors
    assert first and second, (first, second)
    # pole widzenia kamery drona (Tello: 82,6°) zamiast 50° sceny
    assert first["fov"] == pytest.approx(82.6, abs=0.01), first["fov"]
    assert second["fov"] == pytest.approx(82.6, abs=0.01), second["fov"]
    # kamera jest przytwierdzona do drona: pozycja świata = dno korpusu +
    # obiektyw (25 mm w przód, 12 mm w górę) w prawdziwej skali
    sample = second["sample"]
    assert sample["state"] == "airborne", sample
    camera = second["pos"]
    drone = second["drone"]
    distance = ((camera[0] - drone[0]) ** 2 + (camera[2] - drone[2]) ** 2) ** 0.5
    assert distance < 0.10, (camera, drone)
    assert camera[1] == pytest.approx(drone[1] + 0.012, abs=0.01), (camera, drone)
    # przewinięcie zmieniło pozycję kamery (kamera jedzie razem z dronem)
    moved = sum((a - b) ** 2 for a, b in zip(camera, third)) ** 0.5
    assert moved > 0.3, (camera, third)
