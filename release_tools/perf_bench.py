"""Pomiar wydajności interfejsu 3D (Playwright + Chromium) - „ziemniak” i normalny.

Skrypt uruchamia aplikację na wolnym porcie, otwiera ją w Chromium i mierzy
**te same** scenariusze w dwóch profilach:

* ``normal`` - jak na zwykłym komputerze (1600x900, bez throttlingu),
* ``potato`` - „ziemniak”: 1280x720, CPU spowolnione 6x
  (``Emulation.setCPUThrottlingRate``), renderowanie programowe (SwiftShader,
  ``--disable-gpu``).

Mierzone wskaźniki (dla każdego scenariusza):

* FPS średni i **1% najgorszych klatek** (średnia z najwolniejszego 1% klatek),
* czas do pierwszego narysowania sceny (``performance.now()`` przy pierwszej
  klatce z ``renderer.info.render.frame > 0``),
* czas JavaScriptu na klatkę (CDP ``Performance.getMetrics``: ScriptDuration),
* zużycie pamięci JS (``performance.memory.usedJSHeapSize``),
* liczba wywołań rysowania i trójkątów (``renderer.info.render``),
* dla scenariusza odtwarzania: rozmiar danych lotu przesłanych do przeglądarki
  (CDP ``Network``: bajty po kompresji i po dekompresji).

Uruchomienie::

    python release_tools/perf_bench.py                    # oba profile, pełny zestaw
    python release_tools/perf_bench.py --profile potato --repeat 1
    python release_tools/perf_bench.py --only playback --json tmp/perf.json

Wynik: ``docs/wydajnosc.md`` (tabela) i opcjonalnie JSON z surowymi pomiarami.
Skrypt **nic nie optymalizuje** - służy do zmierzenia stanu wyjściowego.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:                                   # uruchomienie jako moduł (testy)
    from release_tools.common import app_version, utf8_console
except ImportError:                    # uruchomienie jako skrypt
    from common import app_version, utf8_console

utf8_console()

ROOT = Path(__file__).resolve().parent.parent
OUT_MD = ROOT / "docs" / "wydajnosc.md"

#: profile sprzętowe (nazwa -> ustawienia przeglądarki i throttling)
PROFILES: Dict[str, Dict[str, Any]] = {
    "normal": {
        "label": "normalny (1600x900, bez throttlingu)",
        "viewport": {"width": 1600, "height": 900},
        "cpu": 1,
        "args": ["--enable-precise-memory-info"],
    },
    "potato": {
        "label": "ziemniak (1280x720, CPU 6x wolniej, SwiftShader)",
        "viewport": {"width": 1280, "height": 720},
        "cpu": 6,
        "args": ["--enable-precise-memory-info", "--disable-gpu",
                 "--use-angle=swiftshader", "--use-gl=angle",
                 "--disable-accelerated-2d-canvas"],
    },
}

#: długi lot: 150 komend w tę i z powrotem (tysiące próbek telemetrii)
LONG_FLIGHT = (
    "from djitellopy import Tello\n"
    "\n"
    "tello = Tello()\n"
    "tello.connect()\n"
    "tello.takeoff()\n"
    + "".join("tello.move_forward(40)\ntello.rotate_clockwise(15)\n" for _ in range(75))
    + "".join("tello.move_back(40)\ntello.rotate_counter_clockwise(15)\n"
              for _ in range(75))
    + "tello.land()\n"
)

#: instrumentacja wstrzykiwana przed wczytaniem aplikacji
INSTRUMENT_JS = """
(() => {
  const perf = { frames: [], lastTs: 0, firstDraw: null, longTasks: 0,
                 renders: [], renderIntervals: [] };
  window.__perf = perf;
  window.__perfReset = () => {
    perf.frames.length = 0;
    perf.lastTs = 0;
    perf.longTasks = 0;
    perf.renders.length = 0;
    perf.renderIntervals.length = 0;
  };
  let patched = false;
  function patchRenderer() {
    const scene = window.__scene;
    if (patched || !scene || !scene.renderer || !scene.renderer.render) return;
    const original = scene.renderer.render.bind(scene.renderer);
    scene.renderer.render = (target, camera) => {
      const now = performance.now();
      const list = perf.renders;
      if (list.length) perf.renderIntervals.push(now - list[list.length - 1]);
      list.push(now);
      return original(target, camera);
    };
    patched = true;
  }
  function loop(ts) {
    patchRenderer();
    if (perf.lastTs) perf.frames.push(ts - perf.lastTs);
    perf.lastTs = ts;
    const scene = window.__scene;
    if (perf.firstDraw === null && scene && scene.renderer
        && scene.renderer.info.render.frame > 0) {
      perf.firstDraw = performance.now();
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  try {
    new PerformanceObserver((list) => { perf.longTasks += list.getEntries().length; })
      .observe({ entryTypes: ['longtask'] });
  } catch (_) { /* brak longtask API */ }
})();
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int) -> subprocess.Popen:
    """Uruchom serwer aplikacji (osobna grupa procesów - łatwe sprzątanie)."""
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags, start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                if response.read().decode().strip() == "ok":
                    return process
        except Exception:                       # noqa: BLE001 - czekamy na start
            pass
        time.sleep(0.3)
    process.kill()
    raise SystemExit("serwer nie wystartował")


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=30,
                       creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        process.kill()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()


def p1_low(intervals: Sequence[float]) -> float:
    """FPS z najgorszych 1% klatek (im dłuższy odstęp, tym gorzej)."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals, reverse=True)
    count = max(1, round(len(ordered) * 0.01))
    worst = statistics.fmean(ordered[:count])
    return 1000.0 / worst if worst > 0 else 0.0


class Session:
    """Jedna sesja przeglądarki dla profilu (nowa strona na scenariusz)."""

    def __init__(self, playwright, profile_name: str, base: str,
                 lite: bool = False) -> None:
        self.playwright = playwright
        self.profile_name = profile_name
        self.profile = PROFILES[profile_name]
        self.base = base
        self.lite = lite
        self.mode = "lite" if lite else "full"
        self.browser = playwright.chromium.launch(args=self.profile["args"])
        self.context = self.browser.new_context(
            viewport=self.profile["viewport"], device_scale_factor=1)
        self.context.add_init_script(INSTRUMENT_JS)
        self.network_log: List[Dict[str, Any]] = []

    def close(self) -> None:
        self.browser.close()

    def new_page(self):
        page = self.context.new_page()
        page.set_default_timeout(120_000)
        cdp = self.context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": self.profile["cpu"]})
        cdp.send("Performance.enable")
        cdp.send("Network.enable")
        requests: Dict[str, str] = {}

        def on_response(params):
            url = params.get("response", {}).get("url", "")
            if "/api/flights/" in url and "live" not in url:
                requests[params["requestId"]] = url

        def on_finished(params):
            url = requests.pop(params.get("requestId"), "")
            if url:
                self.network_log.append({
                    "url": url,
                    "encoded": int(params.get("encodedDataLength") or 0),
                })

        cdp.on("Network.responseReceived", on_response)
        cdp.on("Network.loadingFinished", on_finished)
        page.goto(self.base + ("?lite=1" if self.lite else ""),
                  wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.__scene)", timeout=120_000)
        page.wait_for_function("() => Boolean(window.__featuresReady)", timeout=120_000)
        page.wait_for_function("() => Boolean(window.__editor)", timeout=120_000)
        return page, cdp

    def metrics(self, cdp) -> Dict[str, float]:
        data = cdp.send("Performance.getMetrics")["metrics"]
        return {item["name"]: item["value"] for item in data}

    def measure(self, page, cdp, duration_ms: int, label: str,
                action=None) -> Dict[str, Any]:
        """Zbierz klatki przez ``duration_ms`` i policz wskaźniki.

        :param action: opcjonalna funkcja wykonywana w trakcie pomiaru
            (np. przewijanie suwakiem, przeciąganie punktu)
        """
        page.evaluate("() => window.__perfReset()")
        before = self.metrics(cdp)
        if action is None:
            time.sleep(duration_ms / 1000.0)
        else:
            action(duration_ms)
        after = self.metrics(cdp)
        frames = int(page.evaluate("() => window.__perf.frames.length"))
        intervals = [float(value) for value in
                     page.evaluate("() => window.__perf.frames.slice()")]
        render_intervals = [float(value) for value in
                            page.evaluate("() => window.__perf.renderIntervals.slice()")]
        renders = int(page.evaluate("() => window.__perf.renders.length"))
        heap = page.evaluate(
            "() => (performance.memory ? performance.memory.usedJSHeapSize : 0)")
        render = page.evaluate("""() => {
            const info = window.__scene && window.__scene.renderer.info;
            return info ? {calls: info.render.calls, triangles: info.render.triangles,
                           points: info.render.points, lines: info.render.lines,
                           scale: window.__scene.renderScale} : {};
        }""")
        long_tasks = int(page.evaluate("() => window.__perf.longTasks"))
        first_draw = page.evaluate("() => window.__perf.firstDraw")
        script_s = max(0.0, after.get("ScriptDuration", 0) - before.get("ScriptDuration", 0))
        layout_s = max(0.0, after.get("LayoutDuration", 0) - before.get("LayoutDuration", 0))
        style_s = max(0.0, after.get("RecalcStyleDuration", 0)
                      - before.get("RecalcStyleDuration", 0))
        mean_interval = statistics.fmean(intervals) if intervals else 0.0
        return {
            "scenario": label,
            "profile": self.profile_name,
            "mode": self.mode,
            "frames": frames,
            "fps_avg": round(1000.0 / mean_interval, 1) if mean_interval else 0.0,
            "fps_p1": round(p1_low(intervals), 1),
            "renders": renders,
            "render_fps": round(renders / (duration_ms / 1000.0), 1),
            "render_fps_p1": round(p1_low(render_intervals), 1),
            "js_ms_frame": round(script_s * 1000 / frames, 2) if frames else 0.0,
            "layout_ms_frame": round(layout_s * 1000 / frames, 2) if frames else 0.0,
            "style_ms_frame": round(style_s * 1000 / frames, 2) if frames else 0.0,
            "heap_mb": round(heap / 1024 / 1024, 1),
            "draw_calls": int(render.get("calls") or 0),
            "triangles": int(render.get("triangles") or 0),
            "lines": int(render.get("lines") or 0),
            "render_scale": round(float(render.get("scale") or 1), 2),
            "long_tasks": long_tasks,
            "first_draw_ms": round(float(first_draw), 0) if first_draw else None,
        }


# ------------------------------------------------------------- scenariusze
def basic_square_source() -> str:
    return (ROOT / "examples" / "basic_square.py").read_text(encoding="utf-8")


def set_scrub(page, ratio: float) -> None:
    """Ustaw suwak czasu (``ratio`` 0..1) i wywołaj zdarzenie ``input``."""
    page.evaluate("""(value) => {
        const scrub = document.querySelector('#scrub');
        if (!scrub) return;
        const max = Number(scrub.max) || 1;
        scrub.value = String(value * max);
        scrub.dispatchEvent(new Event('input', { bubbles: true }));
    }""", ratio)


def play(page) -> None:
    if page.inner_text("#btn-play").strip() == "▶":
        page.click("#btn-play")


def pause(page) -> None:
    if page.inner_text("#btn-play").strip() == "⏸":
        page.click("#btn-play")


def run_flight(page, source: str, name: str) -> None:
    """Uruchom skrypt i poczekaj na wczytany lot (bez odtwarzania)."""
    page.evaluate("(src) => window.__editor.setValue(src)", source)
    page.evaluate("() => { const box = document.querySelector('#opt-accel');"
                  " if (box) { box.checked = true; } }")
    page.click("#btn-run")
    page.wait_for_function(
        "() => { const s = document.querySelector('#status-text');"
        "  return Boolean(s) && /Gotowe|Błąd|Przerwano/.test(s.textContent); }",
        timeout=180_000)
    page.wait_for_function(
        "() => Boolean(window.__scene) && window.__scene.samples"
        "  && window.__scene.samples.length > 5", timeout=60_000)
    pause(page)
    set_scrub(page, 0.0)
    time.sleep(0.4)


def measure_flight_payload(page, session: "Session") -> Dict[str, Any]:
    """Rozmiar danych lotu: ile bajtów leci do przeglądarki (po kompresji i bez)."""
    data = page.evaluate("""async () => {
        const list = await (await fetch('/api/flights?limit=1')).json();
        if (!Array.isArray(list) || !list.length) return null;
        const id = list[0].id || list[0].flight_id;
        if (!id) return null;
        const response = await fetch('/api/flights/' + encodeURIComponent(id));
        const text = await response.text();
        return {id, decoded: text.length,
                encoding: response.headers.get('content-encoding') || 'brak'};
    }""")
    if not data:
        return {}
    time.sleep(0.3)
    encoded = [item["encoded"] for item in session.network_log
               if item["url"].rstrip("/").endswith(str(data["id"]))]
    session.network_log.clear()
    return {
        "flight_id": data["id"],
        "flight_bytes": max(encoded) if encoded else None,
        "flight_decoded_bytes": data["decoded"],
        "flight_encoding": data["encoding"],
    }


def scenario_idle(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        time.sleep(1.5)
        return session.measure(page, cdp, 3000, "a) bezczynna scena")
    finally:
        page.close()


def scenario_playback(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        run_flight(page, basic_square_source(), "basic_square.py")
        payload = measure_flight_payload(page, session)
        page.select_option("#speed-select", "1")
        play(page)
        one_x = session.measure(page, cdp, 4000, "b) odtwarzanie 1x")
        page.select_option("#speed-select", "8")
        set_scrub(page, 0.0)
        play(page)
        # przy 8x krótki lot kończy się w ~4 s, więc mierzymy 2,5 s od początku
        eight_x = session.measure(page, cdp, 2500, "b) odtwarzanie 8x")
        eight_x.update(payload)
        return {"b1": one_x, "b8": eight_x}
    finally:
        page.close()


def scenario_long(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        run_flight(page, LONG_FLIGHT, "dlugi_lot.py")
        samples = int(page.evaluate("() => window.__scene.samples.length"))
        play(page)
        playing = session.measure(page, cdp, 3000, "c) długi lot - odtwarzanie")

        def scrub_action(duration_ms: int) -> None:
            steps = max(10, duration_ms // 50)
            for step in range(steps):
                set_scrub(page, (step % 20) / 20.0)
                time.sleep(0.045)

        scrubbing = session.measure(page, cdp, 3000, "c) długi lot - przewijanie",
                                    action=scrub_action)
        playing["samples"] = samples
        scrubbing["samples"] = samples
        return {"c1": playing, "c2": scrubbing}
    finally:
        page.close()


def scenario_obstacles(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        page.click("#tab-btn-obstacles")
        page.locator(".obs-scene").first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#obs-list .obs-item').length > 0",
            timeout=60_000)
        page.click("button[data-tab='tab-script']")
        run_flight(page, basic_square_source(), "basic_square.py")
        play(page)
        return session.measure(page, cdp, 4000, "d) tor przeszkód + odtwarzanie")
    finally:
        page.close()


def scenario_manual(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        page.click("#tab-btn-manual")
        page.locator("[data-mf-start]").click()
        page.wait_for_function(
            "() => window.__manualFlight && window.__manualFlight.state.flying === true",
            timeout=60_000)
        page.mouse.click(120, 120)          # aktywne sterowanie (scena 3D)
        page.wait_for_function(
            "() => window.__manualFlight.state.controlActive === true", timeout=30_000)

        def flight_action(duration_ms: int) -> None:
            page.keyboard.down("ArrowUp")
            time.sleep(duration_ms / 1000.0)
            page.keyboard.up("ArrowUp")

        return session.measure(page, cdp, 3000, "e) lot ręczny", action=flight_action)
    finally:
        page.close()


def scenario_planner(session: Session) -> Dict[str, Any]:
    page, cdp = session.new_page()
    try:
        page.click("#tab-btn-route")
        for _ in range(8):
            page.click("#route-add")
        page.wait_for_function("() => Boolean(window.__routePlanner)", timeout=30_000)
        start = page.evaluate("() => window.__routePlanner.screenOf(0)")
        if not start:
            raise SystemExit("planer: nie udało się zlokalizować punktu na ekranie")
        page.mouse.move(start["x"], start["y"])
        page.mouse.down()

        def drag_action(duration_ms: int) -> None:
            steps = max(10, duration_ms // 60)
            x, y = start["x"], start["y"]
            for step in range(steps):
                x += 6 if (step // 20) % 2 == 0 else -6
                y += 3 if (step // 30) % 2 == 0 else -3
                page.mouse.move(x, y)
                time.sleep(0.05)

        try:
            return session.measure(page, cdp, 3000, "f) planer - przeciąganie punktu",
                                   action=drag_action)
        finally:
            page.mouse.up()
    finally:
        page.close()


SCENARIOS = {
    "idle": scenario_idle,
    "playback": scenario_playback,
    "long": scenario_long,
    "obstacles": scenario_obstacles,
    "manual": scenario_manual,
    "planner": scenario_planner,
}

#: wnioski dopisywane do raportu (uzupełniane po pomiarach)
ANALYSIS = ""


def flatten(result: Any) -> List[Dict[str, Any]]:
    """Wynik scenariusza (dict lub dict dictów) -> lista wierszy."""
    if isinstance(result, dict) and all(isinstance(v, dict) for v in result.values()):
        return list(result.values())
    return [result]


def median_rows(runs: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Mediana wskaźników liczbowych z kolejnych przebiegów."""
    if not runs:
        return []
    base = runs[0]
    merged: List[Dict[str, Any]] = []
    for index, row in enumerate(base):
        item = dict(row)
        for key, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values = [run[index][key] for run in runs
                          if isinstance(run[index].get(key), (int, float))]
                if values:
                    item[key] = round(statistics.median(values), 2)
        merged.append(item)
    return merged


def write_markdown(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> None:
    """Zapisz tabelę wyników do ``docs/wydajnosc.md``."""
    lines = [
        "# Wydajność interfejsu 3D - pomiary",
        "",
        "Pomiary generuje `release_tools/perf_bench.py` (Playwright + Chromium). "
        "Każdy wiersz to mediana z kilku przebiegów tego samego scenariusza - "
        "nie „odczucie”, a liczby z profilera.",
        "",
        f"* data: {meta.get('date', '?')}",
        f"* wersja aplikacji: {meta.get('version', '?')}",
        f"* Chromium: {meta.get('browser', '?')}",
        f"* przebiegi na scenariusz: {meta.get('repeat', '?')}",
        f"* komenda: `{meta.get('command', '?')}`",
        "",
        "## Profile",
        "",
        "| Profil | Okno | CPU | Renderowanie |",
        "|---|---|---|---|",
        "| normalny | 1600x900 | bez throttlingu | GPU (jeśli dostępne) |",
        "| ziemniak | 1280x720 | **6x wolniej** (CDP) | programowe "
        "(SwiftShader, `--disable-gpu`) |",
        "",
        "## Wyniki",
        "",
        "Kolumny: **FPS** = płynność pętli animacji (rAF), **rysowane/s** = ile klatek "
        "naprawdę narysowano (tryb lekki rysuje tylko przy zmianach), "
        "**1% najgorszych** = średnia z najwolniejszego 1% klatek (dla rysowanych, "
        "gdy są dostępne).",
        "",
        "| Scenariusz | Profil | Tryb | FPS | Rysowane/s | 1% najgorszych "
        "| JS ms/klatkę | Layout ms/klatkę | Pamięć JS | Draw calls | Trójkąty | Linie |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['scenario']} | {row['profile']} | {row.get('mode', 'full')} "
            f"| {row['fps_avg']:.1f} | {row.get('render_fps', 0):.1f} "
            f"| {row.get('render_fps_p1') or row['fps_p1']:.1f} "
            f"| {row['js_ms_frame']:.2f} "
            f"| {row.get('layout_ms_frame', 0):.2f} | {row['heap_mb']:.1f} MB "
            f"| {row['draw_calls']} | {row['triangles']} | {row.get('lines', 0)} |")
    first = next((row for row in rows
                  if row.get("first_draw_ms") and row["scenario"].startswith("a)")), None)
    lines += ["", "## Start (czas do pierwszego narysowania sceny)", ""]
    lines.append(f"* profil **{first['profile']}**: {first['first_draw_ms']:.0f} ms"
                 if first else "* brak danych")
    sizes = [row for row in rows
             if row.get("flight_bytes") or row.get("flight_decoded_bytes")]
    lines += ["", "## Rozmiar danych lotu przesłanych do przeglądarki", ""]
    for row in sizes:
        encoded = row.get("flight_bytes") or 0
        decoded = row.get("flight_decoded_bytes") or 0
        lines.append(
            f"* {row['profile']}: **{decoded / 1024:.1f} kB** bez kompresji, "
            f"{encoded / 1024:.1f} kB przez sieć "
            f"(`Content-Encoding: {row.get('flight_encoding', '?')}`, "
            "lot `basic_square.py`)")
    if not sizes:
        lines.append("* brak danych")
    samples = next((row.get("samples") for row in rows if row.get("samples")), None)
    if samples:
        lines.append(f"* długi lot: **{samples} próbek** telemetrii "
                     "(150 komend, scenariusz c)")
    lines += ["", "## Największe źródła spowolnienia", "", ANALYSIS or "(do uzupełnienia)", ""]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark wydajności UI 3D")
    parser.add_argument("--profile", default="both",
                        choices=["normal", "potato", "both"])
    parser.add_argument("--only", default=None,
                        help="scenariusze po przecinku: " + ",".join(SCENARIOS))
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--json", default=None, help="zapisz surowe wyniki do JSON")
    parser.add_argument("--lite", action="store_true",
                        help="mierzone strony otwieraj z ?lite=1 (tryb lekki)")
    parser.add_argument("--no-md", action="store_true",
                        help="nie nadpisuj docs/wydajnosc.md")
    args = parser.parse_args(list(argv) if argv is not None else None)

    from playwright.sync_api import sync_playwright   # import dopiero tutaj

    profiles = ["normal", "potato"] if args.profile == "both" else [args.profile]
    names = list(SCENARIOS) if not args.only else [
        item.strip() for item in args.only.split(",") if item.strip()]
    for name in names:
        if name not in SCENARIOS:
            raise SystemExit(f"nieznany scenariusz: {name}")

    port = free_port()
    server = start_server(port)
    base = f"http://127.0.0.1:{port}"
    all_rows: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    try:
        with sync_playwright() as playwright:
            for profile in profiles:
                session = Session(playwright, profile, base, lite=args.lite)
                meta = {
                    "date": time.strftime("%Y-%m-%d %H:%M"),
                    "version": app_version(),
                    "browser": session.browser.version,
                    "repeat": args.repeat,
                    "mode": "lite" if args.lite else "full",
                    "command": "python release_tools/perf_bench.py "
                               f"--profile {args.profile} --repeat {args.repeat}"
                               + (" --lite" if args.lite else "")
                               + (f" --only {args.only}" if args.only else ""),
                }
                try:
                    for name in names:
                        runs = []
                        for attempt in range(max(1, args.repeat)):
                            print(f"[perf] {profile}: {name} "
                                  f"({attempt + 1}/{args.repeat})", flush=True)
                            try:
                                runs.append(flatten(SCENARIOS[name](session)))
                            except Exception as exc:      # noqa: BLE001 - raport
                                print(f"[perf] BŁĄD {name}/{profile}: {exc}", flush=True)
                        if runs:
                            all_rows.extend(median_rows(runs))
                finally:
                    session.close()
    finally:
        stop_server(server)

    if args.json:
        Path(args.json).write_text(json.dumps(all_rows, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
        print(f"[perf] JSON: {args.json}")
    if not args.no_md and all_rows:
        write_markdown(all_rows, meta)
        print(f"[perf] raport: {OUT_MD}")
    for row in all_rows:
        print(f"[perf] {row['profile']:<6} {row['scenario']:<38} "
              f"FPS {row['fps_avg']:>5.1f}  1% {row['fps_p1']:>5.1f}  "
              f"JS {row['js_ms_frame']:>5.2f} ms  "
              f"calls {row['draw_calls']:>3}  tris {row['triangles']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
