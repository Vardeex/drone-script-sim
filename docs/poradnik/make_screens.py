"""Zrzuty ekranu do poradnika (docs/poradnik/) - Playwright, tylko aplikacja.

Każdy zrzut jest sprawdzany programowo: rozmiar pliku, liczba unikalnych
kolorów (nie może być jednolitym prostokątem) i czy nie jest czarno-biały.
Serwer uruchamiany jest lokalnie na wolnym porcie.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent   # katalog projektu (…/docs/poradnik/..)
OUT = Path(__file__).resolve().parent                    # zrzuty leżą obok tego skryptu
MIN_BYTES = 20000          # mniejszy PNG = prawdopodobnie pusty ekran
MIN_COLORS = 40            # mniej unikalnych kolorów = jednolite tło
#: limit czekania na stan strony (start aplikacji, podsumowanie lotu, podgląd trasy)
TIMEOUT_MS = 30000


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def check_png(path: Path) -> tuple[bool, str]:
    """Sprawdź, czy PNG nie jest pusty (rozmiar + unikalne kolory)."""
    from PIL import Image

    size = path.stat().st_size
    with Image.open(path) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000) or []
        unique = len(colors)
        width, height = image.size
    ok = size >= MIN_BYTES and unique >= MIN_COLORS and width >= 800
    return ok, f"{path.name}: {width}x{height}, {size // 1024} kB, {unique} kolorów"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    # serwer w osobnej sesji (POSIX) / grupie (Windows): sprzątanie nie może
    # trafić w grupę procesów wywołującego (np. pytest albo powłokę CI)
    spawn_kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                    if os.name == "nt" else {"start_new_session": True})
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT),
        **spawn_kwargs)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 950})
            page.goto(base, wait_until="domcontentloaded")

            def shot(name: str) -> None:
                page.screenshot(path=str(OUT / name))
                print("ZRZUT", name)

            def wait_text(selector: str, fragment: str, timeout: int = TIMEOUT_MS) -> None:
                """Czekaj, aż element ``selector`` będzie zawierał ``fragment``."""
                page.wait_for_function(
                    "([sel, text]) => { const node = document.querySelector(sel);"
                    "  return Boolean(node) && node.textContent.includes(text); }",
                    arg=[selector, fragment], timeout=timeout)

            # 1. ekran startowy - czekamy, aż wczytają się wtyczki (zakładka Planer)
            page.locator("#tab-btn-route").wait_for(state="visible", timeout=TIMEOUT_MS)
            shot("01-start.png")

            # 2. przykładowy lot - czekamy na wynik symulacji, nie na czas
            page.select_option("#example-select", "basic_square.py")
            page.wait_for_function(
                "() => document.querySelector('#editor-area').value.includes('takeoff')",
                timeout=TIMEOUT_MS)
            page.click("#btn-run")
            wait_text("#status-text", "Gotowe (OK)")
            page.wait_for_function(
                "() => document.querySelectorAll('#commands-table tbody tr').length > 0",
                timeout=TIMEOUT_MS)
            # kursor z dala od sceny, żeby nie został dymek znacznika
            page.mouse.move(800, 930)
            page.wait_for_timeout(300)          # tylko na zniknięcie dymka pod kursorem
            shot("02-lot.png")

            # 3. tabela komend
            page.click("button[data-tab='tab-commands']")
            page.wait_for_function(
                "() => !document.getElementById('tab-commands').hidden"
                " && document.querySelectorAll('#commands-table tbody tr').length > 0",
                timeout=TIMEOUT_MS)
            shot("03-komendy.png")

            # 4. przeszkody - czekamy na listę scen
            page.click("#tab-btn-obstacles")
            page.wait_for_function(
                "() => document.querySelectorAll('#obs-scene-list *').length > 0",
                timeout=TIMEOUT_MS)
            shot("04-przeszkody.png")

            # 5. planer trasy - 4 punkty; czekamy, aż podgląd policzy 4 punkty
            page.locator("#tab-btn-route").wait_for(state="visible", timeout=TIMEOUT_MS)
            page.click("#tab-btn-route")
            page.locator("#route-place").wait_for(state="visible", timeout=TIMEOUT_MS)
            page.click("#route-place")
            box = page.locator("#viewport canvas").first.bounding_box()
            if box:
                for fx, fy in ((0.35, 0.62), (0.45, 0.75), (0.62, 0.70), (0.68, 0.55)):
                    page.mouse.click(box["x"] + box["width"] * fx,
                                     box["y"] + box["height"] * fy)
            page.wait_for_function(
                "() => document.querySelectorAll('#route-points .route-point').length >= 4",
                timeout=TIMEOUT_MS)
            wait_text("#route-stats", "Punkty: 4")
            page.mouse.move(800, 930)
            page.wait_for_timeout(300)          # tylko na zniknięcie dymka pod kursorem
            shot("05-planer.png")

            # 6. wtyczki - czekamy na karty wtyczek
            page.click("button[data-tab='tab-plugins']")
            page.wait_for_function(
                "() => document.querySelectorAll('#plugins-list .plugin-card').length > 0",
                timeout=TIMEOUT_MS)
            shot("06-wtyczki.png")

            # 7. maty Mission Pad - scenariusz z 4 matami; czekamy na listę scen
            page.click("#tab-btn-obstacles")
            page.wait_for_function(
                "() => [...document.querySelectorAll('#obs-scene-list .obs-scene')]"
                "  .some((b) => /Mission Pady/.test(b.textContent || ''))",
                timeout=TIMEOUT_MS)
            page.click("#obs-scene-list .obs-scene:has-text('Mission Pady')")
            page.wait_for_function(
                "() => [...document.querySelectorAll('#obs-list *')]"
                "  .some((n) => /mata/i.test(n.textContent || ''))",
                timeout=TIMEOUT_MS)
            page.mouse.move(800, 930)
            page.wait_for_timeout(300)          # tylko na zniknięcie dymka pod kursorem
            shot("07-mission-pady.png")

            # 8. tryb realistyczny - przełącznik w nagłówku edytora (zakładka Skrypt)
            page.click("button[data-tab='tab-script']")
            page.wait_for_function(
                "() => !document.getElementById('tab-script').hidden",
                timeout=TIMEOUT_MS)
            page.select_option("#opt-realism", "real")
            page.wait_for_function(
                "() => document.querySelector('#opt-realism').value === 'real'",
                timeout=TIMEOUT_MS)
            shot("08-realizm.png")
            page.select_option("#opt-realism", "ideal")   # wróć do stanu domyślnego

            # 9. kamera FPV - widok z drona w locie. Najpierw wracamy do sceny
            #    „Slalom z bramkami” (poprzedni zrzut wczytał maty - leżą na
            #    trasie kwadratu i zasłaniają widok), ale NIE uruchamiamy
            #    symulacji ponownie: na dole zostaje lot basic_square.py.
            page.click("#tab-btn-obstacles")
            page.click("#obs-scene-list .obs-scene:has-text('Slalom z bramkami')")
            # czekaj, aż to ta scena jest aktywna (przycisk .active) i ma 3 bramki
            page.wait_for_function(
                "() => [...document.querySelectorAll('#obs-scene-list .obs-scene.active')]"
                "  .some((b) => /Slalom z bramkami/.test(b.textContent || ''))",
                timeout=TIMEOUT_MS)
            page.wait_for_function(
                "() => window.__scene && window.__scene.samples"
                "  && window.__scene.samples.length > 10",
                timeout=TIMEOUT_MS)
            page.select_option("#camera-select", "fpv")
            page.wait_for_function(
                "() => window.__scene && window.__scene.cameraMode === 'fpv'",
                timeout=TIMEOUT_MS)
            page.evaluate("""() => {
              const scene = window.__scene;
              const slider = document.querySelector('#scrub');
              // klatka z największym poziomym oddaleniem od startu (trasa kwadratu)
              let best = 0;
              let bestDistance = -1;
              for (const s of scene.samples) {
                const d = Math.hypot(s.x, s.y) + s.z / 100;
                if (s.state === 'airborne' && d > bestDistance) {
                  bestDistance = d;
                  best = s.t;
                }
              }
              slider.value = String(best);
              slider.dispatchEvent(new Event('input', {bubbles: true}));
              slider.dispatchEvent(new Event('change', {bubbles: true}));
            }""")
            page.wait_for_function(
                "() => { const sc = window.__scene;"
                "  return Boolean(sc) && sc.cameraMode === 'fpv' && Boolean(sc._lastSample)"
                "    && sc._lastSample.state === 'airborne'"
                "    && Math.hypot(sc._lastSample.x, sc._lastSample.y) > 80; }",
                timeout=TIMEOUT_MS)
            page.mouse.move(800, 930)
            page.wait_for_timeout(400)          # jedna klatka po przewinięciu
            shot("09-fpv.png")

            browser.close()
    finally:
        # tylko proces serwera (nie grupa): uvicorn nie ma potomków, a grupa
        # mogłaby przypadkiem objąć wywołującego na systemie bez setsid
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)

    results = [check_png(path) for path in sorted(OUT.glob("*.png"))]
    for ok, info in results:
        print(("OK   " if ok else "PUSTY") + " " + info)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
