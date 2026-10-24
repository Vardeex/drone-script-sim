"""Zrzuty ekranu do poradnika (docs/poradnik/) - Playwright, tylko aplikacja.

Każdy zrzut jest sprawdzany programowo: rozmiar pliku, liczba unikalnych
kolorów (nie może być jednolitym prostokątem) i czy nie jest czarno-biały.
Serwer uruchamiany jest lokalnie na wolnym porcie.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "poradnik"
MIN_BYTES = 20000          # mniejszy PNG = prawdopodobnie pusty ekran
MIN_COLORS = 40            # mniej unikalnych kolorów = jednolite tło


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
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1",
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT))
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
            page.wait_for_timeout(3000)

            def shot(name: str) -> None:
                page.screenshot(path=str(OUT / name))
                print("ZRZUT", name)

            shot("01-start.png")

            # 2. przykładowy lot w symulatorze
            page.select_option("#example-select", "basic_square.py")
            page.wait_for_timeout(1200)
            page.click("#btn-run")
            page.wait_for_timeout(6000)
            # kursor z dala od sceny, żeby nie został dymek znacznika
            page.mouse.move(800, 930)
            page.wait_for_timeout(800)
            shot("02-lot.png")

            # 3. tabela komend
            page.click("button[data-tab='tab-commands']")
            page.wait_for_timeout(700)
            shot("03-komendy.png")

            # 4. przeszkody
            page.click("#tab-btn-obstacles")
            page.wait_for_timeout(1500)
            shot("04-przeszkody.png")

            # 5. planer trasy - kilka punktów, żeby było co pokazać
            page.click("#tab-btn-route")
            page.wait_for_timeout(1500)
            page.click("#route-place")
            page.wait_for_timeout(400)
            box = page.locator("#viewport canvas").first.bounding_box()
            if box:
                for fx, fy in ((0.35, 0.62), (0.45, 0.75), (0.62, 0.70), (0.68, 0.55)):
                    page.mouse.click(box["x"] + box["width"] * fx,
                                     box["y"] + box["height"] * fy)
                    page.wait_for_timeout(450)
            page.wait_for_timeout(1200)
            page.mouse.move(800, 930)
            page.wait_for_timeout(500)
            shot("05-planer.png")

            # 6. wtyczki
            page.click("button[data-tab='tab-plugins']")
            page.wait_for_timeout(1200)
            shot("06-wtyczki.png")

            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

    results = [check_png(path) for path in sorted(OUT.glob("*.png"))]
    for ok, info in results:
        print(("OK   " if ok else "PUSTY") + " " + info)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
