"""Test wydajności (marker ``perf``) - profil „ziemniak”, uproszczony.

Nie uruchamia się w zwykłym zestawie (marker ``perf``); w CI tylko ręcznie
(``workflow_dispatch``). Sprawdza **cel wydania**: w trybie lekkim na profilu
„ziemniak” (CPU 6x wolniej, renderowanie programowe, 1280x720) średnio co
najmniej 30 klatek na sekundę i co najmniej 20 FPS w 1% najgorszych klatek.

Mierzy **faktycznie rysowane** klatki (opakowanie ``renderer.render``), bo tryb
lekki rysuje na żądanie - pętla animacji może działać 60 razy na sekundę,
a rysować 5 razy.

Uruchomienie::

    pytest -m perf tests/test_perf_browser.py -q
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
import urllib.request

import pytest

from release_tools.perf_bench import INSTRUMENT_JS, PROFILES, p1_low
from tests.proc_helpers import kill_tree, spawn
from tests.test_route_planner_browser import _free_port

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

pytestmark = [pytest.mark.perf, pytest.mark.browser]

MINI_FLIGHT = """from djitellopy import Tello

tello = Tello()
tello.connect()
tello.takeoff()
tello.move_forward(100)
tello.rotate_clockwise(90)
tello.move_forward(100)
tello.land()
"""

#: cel wydania (specyfikacja zadania 2). Tryb lekki ma limit 30 FPS, więc wynik
#: oscyluje wokół 30 - próg 28 daje zapas na jitter pomiaru, a mimo to wykrywa
#: regresję (np. powrót do 20 FPS).
MIN_AVG_FPS = 28.0
MIN_P1_FPS = 20.0


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


def measure(session, page, seconds: float) -> dict:
    page.evaluate("() => window.__perfReset()")
    time.sleep(seconds)
    intervals = [float(value) for value in
                 page.evaluate("() => window.__perf.renderIntervals.slice()")]
    renders = int(page.evaluate("() => window.__perf.renders.length"))
    mean_interval = statistics.fmean(intervals) if intervals else 0.0
    return {
        "renders": renders,
        "fps_avg": (1000.0 / mean_interval) if mean_interval else 0.0,
        "fps_p1": p1_low(intervals),
        "renders_per_s": renders / seconds,
    }


def test_lite_mode_meets_target_on_potato(server):
    """Tryb lekki: ≥ 30 FPS średnio i ≥ 20 FPS w 1% najgorszych klatek."""
    profile = PROFILES["potato"]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=profile["args"])
        context = browser.new_context(viewport=profile["viewport"],
                                      device_scale_factor=1)
        context.add_init_script(INSTRUMENT_JS)
        page = context.new_page()
        page.set_default_timeout(120_000)
        cdp = context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": profile["cpu"]})
        page.goto(server + "/?lite=1", wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__featuresReady)", timeout=120_000)
        assert page.evaluate("() => Boolean(window.__scene.lite)") is True

        idle = measure(None, page, 2.0)              # bezczynna scena
        page.evaluate("(src) => window.__editor.setValue(src)", MINI_FLIGHT)
        page.click("#btn-run")
        page.wait_for_function(
            "() => { const el = document.querySelector('#status-text');"
            "  return Boolean(el) && /Gotowe/.test(el.textContent); }",
            timeout=120_000)
        page.wait_for_function("() => window.__scene.samples.length > 5",
                               timeout=60_000)
        if page.inner_text("#btn-play").strip() == "▶":
            page.click("#btn-play")                  # odtwarzanie
        playback = measure(None, page, 3.0)
        browser.close()

    assert idle["fps_avg"] >= MIN_AVG_FPS or idle["renders_per_s"] < 5, idle
    assert playback["fps_avg"] >= MIN_AVG_FPS, playback
    assert playback["fps_p1"] >= MIN_P1_FPS, playback
    assert playback["renders_per_s"] <= 34, playback   # limit 30 FPS (+ zapas)
