// Drone Script Simulator - logika interfejsu (spina scenę, panele i API).
import { $, $$, el, fmt, fmtTime, debounce, legendGradient, plural, STATUS_LABEL } from './util.js';
import { FlightTimeline, Player } from './timeline.js';
import { DroneScene } from './scene.js';
import { api, waitForRun } from './api.js';
import { showTooltip, hideTooltip } from './tooltip.js';
import * as panels from './panels.js';
import { registerFeatures, attachSceneLayers } from './boot.js';
import { renderPlugins } from './plugins_tab.js';
import { mountEditor, setEditorValue } from './editor.js';
import { isTypingTarget } from './keys.js';
import {
  addApplyHook, autoDetect, fetchEdition, getMode, initPerf, isForced, isLite,
  onPerfChange, setMode,
} from './perf.js';

//: wersja modułów funkcji (cache-busting lokalnego serwera statyków)
export const ASSET_VERSION = 'v28';

//: edycja wydania - „for_potatoes” startuje w trybie lekkim (patrz edition.json)
export const edition = await fetchEdition();
//: ustawienie wydajności (localStorage + ?lite=1), zanim powstanie scena 3D
const perfState = initPerf();
if (edition.lite_default && !isForced() && getMode() === 'auto') {
  setMode('lite');
}

const state = {
  adapter: 'tello',
  adapters: [],
  runId: null,
  running: false,
  autoPlay: true,
  editorDirty: false,
  scriptName: 'skrypt.py',
};

const timeline = new FlightTimeline();
const scene = new DroneScene($('#viewport'), { lite: isLite() });
const player = new Player(timeline, (t) => onFrame(t));
const marks = { row: -2, line: -1 };

//: stan funkcji (wtyczek): aktywna warstwa sceny + zatrzymanie przy kolizji
export const featureState = {
  statuses: [],
  layers: {},
  stopOnCollision: false,
  findings: [],
  stopped: false,
};

/** Warstwa sceny zarejestrowana przez funkcję (rdzeń nie zna jej wnętrza). */
function layerFor(id) {
  return featureState.layers[id] || null;
}

/** Punkty rozszerzeń dla funkcji (patrz README, „Punkty rozszerzeń”). */
function featureContext() {
  return {
    scene,
    player,
    timeline,
    getLayer: layerFor,
    seek: (t) => {
      player.pause();
      player.seek(Math.max(0, Number(t) || 0));
      updatePlayButton();
    },
    getActiveScene: () => activeScene(),
    setActiveScene: () => {},
    setStopOnCollision: (enabled) => {
      featureState.stopOnCollision = Boolean(enabled);
      featureState.stopped = false;
    },
  };
}

/** Scena zapisana w aktualnie wczytanym locie (do `options.obstacles`). */
function activeScene() {
  const panel = Object.values(panels.featurePanels)[0];
  return panel && typeof panel.getScene === 'function' ? panel.getScene() : null;
}

/** Klucz ustawień symulatora (tryb realistyczny) w localStorage. */
const SIM_SETTINGS_KEY = 'dronesim.sim';

/** Tryb realistyczny z zapisu w przeglądarce (domyślnie idealny). */
function simSettings() {
  try {
    return { realism: false, realism_seed: 1,
      ...JSON.parse(localStorage.getItem(SIM_SETTINGS_KEY) || '{}') };
  } catch (_) {
    return { realism: false, realism_seed: 1 };
  }
}

/** Opcje uruchomienia od funkcji (łączy `getRunOptions` wszystkich paneli). */
function runOptions() {
  let options = {};
  for (const panel of Object.values(panels.featurePanels)) {
    if (typeof panel.getRunOptions === 'function') {
      options = { ...options, ...panel.getRunOptions() };
    }
  }
  // tryb realistyczny: silnik czyta `options.sim` (domyślnie wyłączony)
  const sim = simSettings();
  options.sim = { realism: sim.realism, realism_seed: sim.realism_seed };
  return options;
}

/** Podłącz przełącznik realizmu i seed (zapis w locie do localStorage). */
function bindSimSettings() {
  const select = $('#opt-realism');
  const seed = $('#opt-realism-seed');
  const current = simSettings();
  if (select) select.value = current.realism ? 'real' : 'ideal';
  if (seed) seed.value = String(current.realism_seed);
  const store = () => {
    const settings = {
      realism: select ? select.value === 'real' : false,
      realism_seed: seed ? Math.max(0, Math.round(Number(seed.value) || 0)) : 1,
    };
    try { localStorage.setItem(SIM_SETTINGS_KEY, JSON.stringify(settings)); } catch (_) { /* tryb prywatny */ }
  };
  select?.addEventListener('change', store);
  seed?.addEventListener('change', store);
}

/** Pierwsza kolizja z raportu funkcji do chwili t (lub null). */
function currentCollision(t) {
  for (const panel of Object.values(panels.featurePanels)) {
    const findings = typeof panel.getFindings === 'function' ? panel.getFindings() : [];
    const hit = findings.find((f) => f.level === 'collision' && f.t <= t + 1e-6);
    if (hit) return hit;
  }
  return null;
}

//: limit czasu wykonania skryptu w UI (sekundy czasu rzeczywistego)
const RUN_TIMEOUT_S = 60;

function setStatus(text, kind = '', extra = '') {
  const bar = $('#status-bar');
  bar.className = kind;
  const holder = $('#status-text');
  holder.innerHTML = '';
  if (kind === 'running') holder.append(el('span', { class: 'spinner' }));
  holder.append(document.createTextNode(text));
  $('#status-extra').textContent = extra;
}

function updatePlayButton() {
  const btn = $('#btn-play');
  if (!btn) return;
  btn.textContent = player.playing ? '⏸' : '▶';
  btn.title = player.playing ? 'Pauza (spacja)' : 'Odtwórz (spacja)';
}

function currentScriptName() {
  // nazwa skryptu wpisywana w edytorze/wgranego pliku (nie zmieniana przez wczytane loty)
  return state.scriptName || 'skrypt.py';
}

function setScriptName(name) {
  state.scriptName = name || 'skrypt.py';
  $('#editor-name').textContent = state.scriptName;
}

function switchTab(id) {
  $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === id));
  $$('.tab-content').forEach((c) => { c.hidden = c.id !== id; });
  // zakładka wtyczek pobiera świeżą listę przy każdym otwarciu
  if (id === 'tab-plugins') renderPlugins();
}

/** Informacje o wersji i edycji w nagłówku, stopce i tytule okna. */
function applyEditionInfo() {
  const name = edition.display_name || edition.version || '';
  const label = name ? `Drone Script Simulator ${name}` : 'Drone Script Simulator';
  document.title = label;
  const footer = $('#footer-edition');
  if (footer) footer.textContent = label;
  const badge = $('#edition-badge');
  if (badge) {
    badge.hidden = edition.edition !== 'for_potatoes';
    badge.textContent = edition.edition === 'for_potatoes' ? 'for_potatoes' : '';
    badge.title = 'Wydanie dla słabych komputerów (tryb lekki domyślnie)';
  }
}

/** Opcje wyłączone domyślnie w edycji for_potatoes (można włączyć ręcznie). */
function applyEditionDefaults() {
  const features = edition.features || {};
  if (!features.fpv) {
    const select = $('#camera-select');
    const fpv = select ? select.querySelector('option[value="fpv"]') : null;
    if (fpv) fpv.disabled = true;
  }
  if (!features.realism) {
    // tryb realistyczny zostaje dostępny, ale domyślnie „idealny”
    const select = $('#opt-realism');
    if (select) select.value = 'ideal';
  }
}

// ---------------------------------------------------------- tryb wydajności
/** Odstęp odświeżania paneli w trybie lekkim (10 razy na sekundę). */
const LITE_UI_INTERVAL_MS = 100;
let lastUiUpdate = 0;

/** Opcje kamery niedostępne w trybie lekkim (FPV = dodatkowa praca co klatkę). */
function updateCameraOptions(lite) {
  const select = $('#camera-select');
  const fpv = select ? select.querySelector('option[value="fpv"]') : null;
  if (!select || !fpv) return;
  fpv.disabled = lite;
  fpv.textContent = lite ? 'FPV (wyłączone w trybie lekkim)' : 'FPV (z drona)';
  if (lite && select.value === 'fpv') {
    select.value = 'orbit';
    scene.setCameraMode('orbit');
  }
}

/** Odśwież interfejs po zmianie trybu (select, kamera, panele funkcji). */
export function applyLiteUi(lite) {
  const select = $('#perf-mode');
  if (select) select.value = lite ? 'lite' : (isForced() ? 'lite' : getMode());
  updateCameraOptions(lite);
  document.body.classList.toggle('lite-mode', Boolean(lite));
  $$('.perf-hint').forEach((node) => { node.hidden = !lite; });
  lastUiUpdate = 0;                 // po zmianie trybu odśwież panele od razu
  if (timeline.samples && timeline.samples.length) {
    onFrame(player.t || 0);
  }
}

/** Propozycja trybu lekkiego w pasku stanu (nie zasłania interfejsu). */
function proposeLite({ fps, enable, disable, neverAsk }) {
  const text = $('#status-text');
  const extra = $('#status-extra');
  if (!text || !extra) return;
  text.textContent = `Twój komputer działa wolno (${Math.round(fps)} FPS) `
    + '- włączyć tryb lekki?';
  extra.innerHTML = '';
  const add = (label, handler, primary) => {
    const button = el('button', { class: primary ? 'primary' : 'ghost', text: label });
    button.style.marginLeft = '6px';
    button.addEventListener('click', () => {
      handler();
      extra.innerHTML = '';
      text.textContent = isLite()
        ? 'Tryb lekki włączony - możesz go zmienić w „Wydajność” na dole.'
        : 'Tryb pełny - ustawienie zapamiętane.';
      applyLiteUi(isLite());
    });
    extra.append(button);
  };
  add('Tak', enable, true);
  add('Nie', disable, false);
  add('Nie pytaj więcej', neverAsk, false);
}

//: scena i panele reagują na zmianę trybu wydajności
addApplyHook((lite) => {
  scene.setQuality(lite);
  applyLiteUi(lite);
});
onPerfChange(() => applyLiteUi(isLite()));

function onFrame(t) {
  const sample = timeline.sampleAt(t);
  scene.update(sample);
  updateHud(sample, t);
  // punkt rozszerzeń nr 4: warstwy funkcji dostają czas odtwarzania
  for (const status of Object.values(featureState.layers)) {
    status.instance.setMarkersTime?.(t);
  }
  // opcjonalne zatrzymanie odtwarzania przy kolizji (ustawienie funkcji)
  if (featureState.stopOnCollision && !featureState.stopped) {
    const hit = currentCollision(t);
    if (hit) {
      featureState.stopped = true;
      player.pause();
      setStatus(`Kolizja: ${hit.message}`, 'error');
    }
  }
  // tryb lekki: panele (telemetria, komendy) odświeżamy najwyżej 10 razy na
  // sekundę. Poza odtwarzaniem (pauza, przewijanie) zawsze od razu, żeby
  // suwak i etykiety były dokładne.
  const now = performance.now();
  if (isLite() && player.playing && now - lastUiUpdate < LITE_UI_INTERVAL_MS) {
    return;
  }
  lastUiUpdate = now;
  const scrub = $('#scrub');
  if (scrub) scrub.value = String(t);
  const label = $('#time-label');
  if (label) label.textContent = `${fmtTime(t)} / ${fmtTime(timeline.duration)}`;

  const index = timeline.eventIndexAt(t);
  const event = index >= 0 ? timeline.events[index] : null;
  const hud = $('#hud-command');
  if (hud) {
    const maneuver = event && event.maneuver ? `◆ ${event.maneuver} · ` : '';
    hud.textContent = event
      ? `${maneuver}#${event.index} ${event.command}(${(event.args || []).map(String).join(', ')})`
      : '—';
  }
  // w tabeli komend manewry są zwinięte w jeden wiersz - szukamy wiersza dla chwili t
  const rowIndex = panels.commandRowIndexAt(timeline, t);
  if (marks.row !== rowIndex) {
    panels.highlightCommandRow(rowIndex);
    marks.row = rowIndex;
  }
  const line = event ? event.line : null;
  if (marks.line !== line) {
    panels.highlightCodeLine(line);
    marks.line = line;
  }
  updatePlayButton();
}

function updateHud(sample, t) {
  $('#hud-time').textContent = fmtTime(t);
  $('#hud-state').textContent = STATUS_LABEL[sample.state] || sample.state;
  $('#hud-pos').textContent = `${fmt(sample.x, 0)} / ${fmt(sample.y, 0)} / ${fmt(sample.z, 0)} cm`;
  $('#hud-alt').textContent = `${fmt(sample.z / 100, 2)} m`;
  $('#hud-yaw').textContent = `${fmt(sample.yaw, 0)}°`;
  $('#hud-speed').textContent = `${fmt(Math.hypot(sample.vx, sample.vy, sample.vz), 0)} cm/s`;
  const battery = $('#hud-battery');
  battery.textContent = `${fmt(sample.battery, 1)}%`;
  battery.style.color = sample.battery < 20 ? '#f87171' : '';
}
function loadFlight(data, meta = {}) {
  timeline.load(data, meta);
  marks.row = -2;
  marks.line = -1;
  const errorLines = timeline.errors.filter((e) => e.line).map((e) => e.line);
  panels.renderCodeView(timeline.source, errorLines);
  panels.renderCommands(timeline, (t) => {
    player.pause();
    player.seek(t);
    updatePlayButton();
  });
  panels.renderIssues(timeline, (line) => {
    switchTab('tab-script');
    panels.highlightCodeLine(line);
  });
  panels.renderConsole(timeline);
  panels.renderStats(timeline);
  setScriptName(timeline.scriptName);

  // punkt rozszerzeń nr 4: funkcje dostają wczytany lot (np. własną scenę + raport)
  for (const status of Object.values(featureState.layers)) {
    const api = panels.featurePanels[status.id];
    if (api && typeof api.onFlightLoaded === 'function') {
      try {
        api.onFlightLoaded(data);
      } catch (err) {
        console.error(`Funkcja ${status.id}: błąd wczytywania lotu`, err);
      }
    }
  }
  featureState.stopped = false;

  const maxHeight = timeline.maxHeight();
  scene.setFlight(timeline.samples, timeline.events, maxHeight);
  $('#legend-min').textContent = '0 m';
  $('#legend-max').textContent = `${fmt(Math.max(maxHeight, 100) / 100, 1)} m`;
  $('#scrub').max = String(Math.max(timeline.duration, 0.01));
  if (!state.editorDirty && timeline.source) setEditorValue(timeline.source);

  player.pause();
  player.setTime(0);
  updatePlayButton();
  scene.fitView();
  onFrame(0);
}

/** Menu w nagłówku („☰”) - otwórz/zamknij, zamknij po kliknięciu poza menu. */
function bindAppMenu() {
  const button = $('#btn-menu');
  const menu = $('#app-menu');
  if (!button || !menu) return;
  const setOpen = (open) => {
    menu.hidden = !open;
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) menu.querySelector('.menu-item')?.focus();
  };
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    setOpen(menu.hidden);
  });
  document.addEventListener('click', (event) => {
    if (menu.hidden) return;
    if (!$('#app-menu-wrap').contains(event.target)) setOpen(false);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !menu.hidden) {
      setOpen(false);
      button.focus();
    }
  });
  $('#menu-shutdown').addEventListener('click', () => {
    setOpen(false);
    shutdownApp();
  });
}

/**
 * Zakończ program: potwierdzenie → ``POST /api/shutdown`` → ekran końcowy.
 *
 * Endpoint przyjmuje żądania tylko z tego komputera (127.0.0.1), zatrzymuje
 * uruchomione skrypty i kończy serwer; launcher ``DroneSim.exe`` kończy się
 * razem z nim (dostaje plik ``--stop-file``). Gdy serwer zdąży się zamknąć
 * przed odpowiedzią, ``fetch`` rzuci błąd - to normalne, pokazujemy ekran.
 */
async function shutdownApp() {
  if (!window.confirm('Zamknąć DroneSim?')) return;
  const button = $('#btn-shutdown');
  if (button) button.disabled = true;
  try {
    await fetch('/api/shutdown', { method: 'POST' });
  } catch (err) {
    console.warn('shutdown: brak odpowiedzi serwera (to oczekiwane)', err);
  }
  showShutdownScreen();
}

/** Ekran „Program zakończony” - przykrywa interfejs po zamknięciu serwera. */
function showShutdownScreen() {
  player.pause();
  if ($('#shutdown-screen')) return;
  const box = el('div', { id: 'shutdown-screen', class: 'shutdown-screen' }, [
    el('div', { class: 'shutdown-card' }, [
      el('p', { class: 'shutdown-text',
        text: 'Program zakończony – możesz zamknąć tę kartę.' }),
    ]),
  ]);
  document.body.append(box);
}

async function runSimulation() {
  const source = $('#editor-area').value;
  if (!source.trim()) {
    setStatus('Skrypt jest pusty - wpisz kod lub wczytaj przykład.', 'error');
    return;
  }
  if (state.running) return;
  state.running = true;
  state.runId = null;
  $('#btn-run').disabled = true;
  $('#btn-stop').disabled = false;
  setStatus('Symulacja w toku...', 'running');
  timeline.reset();
  panels.renderCodeView(source);
  player.pause();
  player.setTime(0);

  try {
    const started = await api.run({
      source,
      adapter: state.adapter,
      script_name: currentScriptName(),
      accel: $('#opt-accel').checked,
      save: true,
      timeout: RUN_TIMEOUT_S,
      options: runOptions(),
    });
    state.runId = started.id;
    const startedAt = Date.now();
    const result = await waitForRun(started.id, (update) => {
      if (update.status === 'running' && update.live) renderLive(update.live, startedAt);
    }, { maxMs: (RUN_TIMEOUT_S + 30) * 1000 });
    if (result.status === 'failed') throw new Error(result.error || 'Błąd serwera.');
    if (!result.flight) throw new Error('Brak wyniku lotu.');
    loadFlight(result.flight, {
      source, scriptName: currentScriptName(), flightId: result.flight_id, adapter: state.adapter,
    });
    const errors = result.flight.errors.length;
    const warnings = result.flight.warnings.length;
    const label = STATUS_LABEL[result.flight.status] || result.flight.status;
    const stopped = result.flight.status === 'stopped';
    setStatus(stopped
      ? `Przerwano - symulacja ${fmtTime(result.flight.duration)} (telemetria do momentu Stop)`
      : `Gotowe (${label}) - symulacja ${fmtTime(result.flight.duration)}, `
        + `obliczenia ${fmt(result.real_seconds, 2)} s`,
    stopped ? '' : (errors ? 'error' : 'ok'),
    `${errors} ${plural(errors, 'błąd', 'błędy', 'błędów')} · `
    + `${warnings} ${plural(warnings, 'ostrzeżenie', 'ostrzeżenia', 'ostrzeżeń')}`);
    switchTab(errors ? 'tab-issues' : 'tab-stats');
    if (state.autoPlay && timeline.duration > 0) {
      player.setTime(0);
      player.play();
      updatePlayButton();
    }
    loadHistory();
  } catch (err) {
    console.error('runSimulation', err.stack || err.message);
    setStatus(`Błąd: ${err.message}`, 'error');
  } finally {
    state.running = false;
    $('#btn-run').disabled = false;
    $('#btn-stop').disabled = true;
  }
}

function renderLive(live, startedAt) {
  const now = live.now || 0;
  const samples = timeline.samples.slice();
  const tail = live.samples_tail || [];
  if (tail.length) {
    const lastT = samples.length ? samples[samples.length - 1].t : -1;
    for (const s of tail) if (s.t > lastT) samples.push(s);
  }
  const last = samples.length ? samples[samples.length - 1] : null;
  const current = {
    ...(last || { x: 0, y: 0, z: 0, yaw: 0, vx: 0, vy: 0, vz: 0, battery: 100, state: 'idle' }),
    t: now,
  };
  samples.push(current);
  const events = live.events || [];
  const maxHeight = samples.reduce((m, s) => Math.max(m, s.z), 1);
  scene.setFlight(samples, events, maxHeight);
  scene.update(current);
  updateHud(current, now);
  const ev = events.length ? events[events.length - 1] : null;
  $('#hud-command').textContent = ev ? `#${ev.index} ${ev.command}` : '—';
  panels.highlightCodeLine(ev ? ev.line : null);
  const realElapsed = (Date.now() - startedAt) / 1000;
  setStatus('Symulacja w toku...', 'running',
    `${events.length} komend · ${current.state} · ${fmt(realElapsed, 1)} s`);
}


async function loadExamples() {
  try {
    const list = await api.examples();
    const select = $('#example-select');
    select.innerHTML = '<option value="">— przykład —</option>';
    for (const item of list) {
      select.append(el('option', { value: item.name, text: item.name }));
    }
  } catch (err) {
    setStatus(`Nie udało się pobrać przykładów: ${err.message}`, 'error');
  }
}

async function loadExample(name) {
  const data = await api.example(name);
  setEditorValue(data.source);
  setScriptName(data.name);
  state.editorDirty = false;
  panels.renderCodeView(data.source);
}

async function loadHistory() {
  try {
    const items = await api.flights(20);
    const box = $('#history-list');
    box.innerHTML = '';
    if (!items.length) {
      box.append(el('div', { class: 'empty', text: 'Brak zapisanych lotów.' }));
      return;
    }
    for (const item of items) box.append(historyRow(item));
  } catch (err) {
    setStatus(`Historia: ${err.message}`, 'error');
  }
}

// ------------------------------------- lot rzeczywisty: import i porównanie
//: id ostatnio wgranego lotu rzeczywistego (porównujemy go z wybranym symulowanym)
let realFlightId = null;

async function onImportReal(event) {
  const file = event.target?.files?.[0];
  if (event.target) event.target.value = '';
  if (!file) return;
  const body = new FormData();
  body.append('file', file);
  try {
    const response = await fetch('/api/flights/import-real', { method: 'POST', body });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || response.statusText);
    realFlightId = data.id;
    setStatus(`Wczytano lot rzeczywisty „${data.name}” (${data.samples} próbek, `
      + `${fmtTime(data.duration)})`, 'ok');
    await loadHistory();
    await fillCompareSelect();
  } catch (err) {
    setStatus(`Import lotu rzeczywistego: ${err.message}`, 'error');
  }
}

/** Wypełnij listę lotów symulowanych do porównania. */
async function fillCompareSelect() {
  if (!realFlightId) return;
  try {
    const items = (await api.flights(30))
      .filter((item) => item.id !== realFlightId && item.source !== 'real');
    const select = $('#compare-sim');
    select.innerHTML = '';
    for (const item of items) {
      const when = (item.created_at || '').replace('T', ' ').slice(0, 19);
      select.append(el('option', {
        value: item.id, text: `${item.script_name || item.id} (${when})`,
      }));
    }
    if (!items.length) {
      select.append(el('option', { value: '', text: 'brak lotów symulowanych' }));
    }
    $('#compare-row').hidden = false;
    $('#compare-result').hidden = true;
  } catch (err) {
    setStatus(`Lista lotów do porównania: ${err.message}`, 'error');
  }
}

async function onCompare() {
  const simId = $('#compare-sim').value;
  if (!realFlightId || !simId) return;
  try {
    const response = await fetch('/api/flights/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ real_id: realFlightId, sim_id: simId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || response.statusText);
    renderComparison(data);
  } catch (err) {
    setStatus(`Porównanie lotów: ${err.message}`, 'error');
  }
}

/** Raport odchyłek + dwa tory na jednej scenie 3D. */
function renderComparison(data) {
  const box = $('#compare-result');
  box.hidden = false;
  box.innerHTML = '';
  const report = data.report;
  const metrics = [
    ['Maks. odchyłka', `${report.max_error_cm} cm`],
    ['Średnia', `${report.mean_error_cm} cm`],
    ['95. percentyl', `${report.p95_error_cm} cm`],
    ['Na końcu lotu', `${report.final_error_cm} cm`],
    ['Droga drona', `${report.real_path_cm} cm`],
    ['Droga symulacji', `${report.sim_path_cm} cm`],
  ];
  const grid = el('div', { class: 'stats-grid' });
  for (const [label, value] of metrics) {
    grid.append(el('div', { class: 'stat' }, [
      el('div', { class: 'label', text: label }),
      el('div', { class: 'value', text: value }),
    ]));
  }
  box.append(grid);
  const list = el('ul', { class: 'hint' });
  for (const hint of report.hints) list.append(el('li', { text: hint }));
  box.append(list);
  box.append(el('div', {
    class: 'hint',
    text: 'Scena 3D: tor pomarańczowy = dron rzeczywisty, niebieski = symulacja.',
  }));
  // oba tory na jednej scenie (kolory jak w opisie wyżej)
  scene?.setComparison?.({
    real: (data.series || []).map((row) => row.real),
    sim: (data.series || []).map((row) => row.sim),
  });
  setStatus('Porównanie gotowe - tory widać w scenie 3D.', 'ok');
}

function historyRow(item) {
  const row = el('div', { class: 'flight-item' });
  const isReal = item.source === 'real';
  row.append(el('div', {}, [
    el('div', { class: 'name', text: (isReal ? '🛰 ' : '') + (item.script_name || item.id) }),
    el('div', {
      class: 'meta',
      text: `${(item.created_at || '').replace('T', ' ').slice(0, 19)} · `
        + `${fmtTime(item.duration)} · ${item.events} komend · `
        + `${item.errors || 0} bł. · ${item.warnings || 0} ostr.`
        + (isReal ? ' · lot rzeczywisty' : ''),
    }),
  ]));
  row.append(el('div', { class: 'actions row' }, [
    el('button', {
      class: 'ghost', title: 'Wczytaj lot', text: '▶',
      onclick: (e) => { e.stopPropagation(); openFlight(item.id); },
    }),
    el('button', {
      class: 'ghost', title: 'Pobierz JSON', text: '⬇',
      onclick: (e) => {
        e.stopPropagation();
        window.location.href = `/api/flights/${item.id}/json`;
      },
    }),
    el('button', {
      class: 'ghost', title: 'Usuń lot', text: '🗑',
      onclick: async (e) => {
        e.stopPropagation();
        if (!window.confirm(`Usunąć lot ${item.script_name}?`)) return;
        try {
          await api.deleteFlight(item.id);
        } catch (err) {
          setStatus(`Nie udało się usunąć: ${err.message}`, 'error');
        }
        if (timeline.flightId === item.id) {
          timeline.reset();
          scene.setFlight([], [], 1);
        }
        loadHistory();
      },
    }),
  ]));
  row.addEventListener('click', () => openFlight(item.id));
  return row;
}

async function openFlight(id) {
  try {
    const data = await api.flight(id);
    state.editorDirty = false;
    loadFlight(data, { flightId: id, source: data.script_source });
    setStatus(`Wczytano lot ${id}.`, 'ok');
  } catch (err) {
    setStatus(`Nie udało się wczytać lotu: ${err.message}`, 'error');
  }
}

async function loadAdapters() {
  try {
    state.adapters = await api.adapters();
    const select = $('#adapter-select');
    select.innerHTML = '';
    for (const item of state.adapters) {
      select.append(el('option', { value: item.id, text: item.name }));
    }
    setAdapter(select.value || 'tello');
  } catch (err) {
    setStatus(`Brak adapterów: ${err.message}`, 'error');
  }
}

function setAdapter(id) {
  state.adapter = id;
  const info = state.adapters.find((a) => a.id === id);
  $('#adapter-badge').textContent = info ? info.name : id;
  const limits = info?.limits;
  if (limits) {
    $('#adapter-badge').title = `Ruch ${limits.move_min_cm}-${limits.move_max_cm} cm, `
      + `obrót ${limits.rotate_min_deg}-${limits.rotate_max_deg}°, `
      + `prędkość ${limits.speed_min}-${limits.speed_max} cm/s`;
  }
}

function seekPrev() {
  const t = timeline.prevEventTime(player.t);
  player.pause();
  player.seek(t === null ? Math.max(0, player.t - 1) : t);
  updatePlayButton();
}

function seekNext() {
  const t = timeline.nextEventTime(player.t);
  player.pause();
  if (t !== null) player.seek(t);
  updatePlayButton();
}

async function loadUploadedFile(file) {
  if (!file) return;
  const text = await file.text();
  setEditorValue(text);
  setScriptName(file.name);
  state.editorDirty = true;
  panels.renderCodeView(text);
  setStatus(`Wczytano ${file.name} - kliknij "Uruchom symulację".`, '');
}

async function importFlightFile(file) {
  if (!file) return;
  try {
    const result = await api.importFlight(file);
    loadFlight(result.flight, { flightId: result.id, source: result.flight.script_source });
    setStatus(`Zaimportowano lot ${result.id}.`, 'ok');
    loadHistory();
  } catch (err) {
    setStatus(`Import nieudany: ${err.message}`, 'error');
  }
}

function bindUi() {
  $$('#tabs button').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  const refreshPlugins = $('#btn-refresh-plugins');
  if (refreshPlugins) refreshPlugins.addEventListener('click', () => renderPlugins());

  $('#btn-run').addEventListener('click', runSimulation);
  $('#btn-shutdown').addEventListener('click', shutdownApp);
  bindAppMenu();
  $('#btn-stop').addEventListener('click', async () => {
    if (!state.runId || !state.running) return;
    $('#btn-stop').disabled = true;
    setStatus('Przerywanie symulacji...', 'running');
    try {
      const result = await api.stopRun(state.runId);
      if (!result.stopped) setStatus('Symulacja już się zakończyła.', '');
    } catch (err) {
      setStatus(`Nie udało się przerwać: ${err.message}`, 'error');
    }
  });

  $('#btn-play').addEventListener('click', () => { player.toggle(); updatePlayButton(); });
  $('#btn-prev').addEventListener('click', seekPrev);
  $('#btn-next').addEventListener('click', seekNext);
  $('#scrub').addEventListener('input', (e) => {
    player.pause();
    player.seek(Number(e.target.value));
    updatePlayButton();
  });
  $('#speed-select').addEventListener('change', (e) => {
    player.speed = Number(e.target.value);
    scene.setPlaybackRate(player.speed);
  });
  // tryb wydajności: Automatycznie / Pełna / Lekka (zapamiętywane lokalnie)
  const perfSelect = $('#perf-mode');
  if (perfSelect) {
    perfSelect.value = isLite() ? 'lite' : getMode();
    perfSelect.addEventListener('change', (e) => {
      setMode(e.target.value);
      setStatus(e.target.value === 'lite'
        ? 'Tryb lekki: mniej szczegółów, więcej FPS.'
        : (e.target.value === 'full'
          ? 'Tryb pełny: wszystkie efekty włączone.'
          : 'Wydajność: automatycznie (pomiar przy starcie).'), '');
    });
  }
  $('#camera-select').addEventListener('change', (e) => {
    const mode = e.target.value;
    scene.setCameraMode(mode);
    // FPV patrzy z drona - kadrowanie trasy nie ma sensu
    if (mode !== 'orbit' && mode !== 'fpv') {
      scene.fitView();
      scene.setCameraMode(mode);
    }
  });
  $('#btn-fit').addEventListener('click', () => {
    if (scene.cameraMode === 'orbit') {
      // swobodna: kadr na całą trasę bez zmiany kierunku patrzenia
      scene.frameFlight();
      return;
    }
    scene.setCameraMode('orbit');
    $('#camera-select').value = 'orbit';
    scene.fitView();
  });

  // rozmiar modelu drona (tylko model - trasa i telemetria bez zmian)
  const sizeSelect = $('#drone-size');
  if (sizeSelect) {
    scene.setDroneSize(Number(sizeSelect.value));
    sizeSelect.addEventListener('change', (e) => {
      scene.setDroneSize(Number(e.target.value));
      if (scene.cameraMode === 'follow') scene.setCameraMode('follow');
    });
  }
  // osłony śmigieł
  const guardsBtn = $('#btn-guards');
  if (guardsBtn) {
    guardsBtn.addEventListener('click', () => {
      const on = !guardsBtn.classList.contains('on');
      guardsBtn.classList.toggle('on', on);
      scene.setGuards(on);
    });
  }
  // strzałka kierunku przodu na cieniu
  const arrowBtn = $('#btn-shadow-arrow');
  if (arrowBtn) {
    arrowBtn.addEventListener('click', () => {
      const on = !arrowBtn.classList.contains('on');
      arrowBtn.classList.toggle('on', on);
      scene.setShadowArrow(on);
    });
  }

  $('#adapter-select').addEventListener('change', (e) => setAdapter(e.target.value));

  $('#btn-open').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', async (e) => {
    await loadUploadedFile(e.target.files?.[0]);
    e.target.value = '';
  });
  $('#btn-clear').addEventListener('click', () => {
    setEditorValue('');
    setScriptName('skrypt.py');
    state.editorDirty = true;
    panels.renderCodeView('');
  });
  $('#editor-area').addEventListener('input', () => { state.editorDirty = true; });
  $('#editor-area').addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    e.preventDefault();
    const area = e.target;
    const start = area.selectionStart;
    const end = area.selectionEnd;
    area.value = `${area.value.slice(0, start)}    ${area.value.slice(end)}`;
    area.selectionStart = start + 4;
    area.selectionEnd = start + 4;
  });
  $('#example-select').addEventListener('change', async (e) => {
    const name = e.target.value;
    e.target.value = '';
    if (!name) return;
    try {
      await loadExample(name);
    } catch (err) {
      setStatus(`Nie udało się wczytać przykładu: ${err.message}`, 'error');
    }
  });

  $('#btn-json').addEventListener('click', () => {
    if (!timeline.flightId) { setStatus('Brak zapisanego lotu do pobrania.', 'error'); return; }
    window.location.href = `/api/flights/${timeline.flightId}/json`;
  });
  $('#btn-csv').addEventListener('click', () => {
    if (!timeline.flightId) { setStatus('Brak zapisanego lotu do eksportu.', 'error'); return; }
    window.location.href = `/api/flights/${timeline.flightId}/csv`;
  });
  $('#btn-import').addEventListener('click', () => $('#import-input').click());
  $('#import-input').addEventListener('change', async (e) => {
    await importFlightFile(e.target.files?.[0]);
    e.target.value = '';
  });
  $('#btn-refresh-history').addEventListener('click', loadHistory);
  $('#btn-import-real').addEventListener('click', () => $('#import-real-input').click());
  $('#import-real-input').addEventListener('change', onImportReal);
  $('#btn-compare').addEventListener('click', onCompare);
}

function bindCanvasPicking() {
  const canvas = scene.renderer.domElement;
  const viewport = $('#viewport');
  const onMove = debounce((x, y) => {
    const event = scene.pick(x, y);
    canvas.style.cursor = event ? 'pointer' : '';
    showTooltip(event, x, y, viewport);
  }, 15);
  canvas.addEventListener('mousemove', (e) => onMove(e.clientX, e.clientY));
  canvas.addEventListener('mouseleave', () => {
    hideTooltip();
    canvas.style.cursor = '';
  });
  canvas.addEventListener('click', (e) => {
    const event = scene.pick(e.clientX, e.clientY);
    if (!event) return;
    player.pause();
    player.seek(event.t);
    updatePlayButton();
    switchTab('tab-commands');
  });
}

function bindKeyboard() {
  document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd+Enter uruchamia skrypt także z edytora - to świadomy skrót globalny
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runSimulation();
      return;
    }
    // Piszesz w edytorze/polu/oknie dialogowym? Klawisz należy do pola:
    // bez preventDefault, bez play/pauzy i bez przewijania.
    if (isTypingTarget(e)) return;
    if (e.key === ' ') {
      e.preventDefault();
      player.toggle();
      updatePlayButton();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      seekPrev();
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      seekNext();
    }
  });
}

function normalizeText(node) {
  // Znormalizuj różne rodzaje spacji w etykietach (np. "▶\u00a0Uruchom"),
  // bez ruszania pustych przycisków ikonowych.
  if (!node) return;
  const text = node.textContent
    .replace(/[\u00a0\u2007\u2009\u202f\u2060]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (text) node.textContent = text;
}

function blend(a, b, t) {
  const c = a.map((value, index) => Math.round(value + (b[index] - value) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

async function init() {
  try {
    document.querySelectorAll('button').forEach((btn) => {
      if (btn.id !== 'btn-play') normalizeText(btn);
    });
    $('#legend-bar').style.background = legendGradient();
    mountEditor();               // CodeMirror 6 nad ukrytą textarea #editor-area
    bindUi();
    bindSimSettings();
    bindCanvasPicking();
    bindKeyboard();
    // punkt rozszerzeń nr 4: funkcje (wtyczki) - panel UI + warstwa sceny 3D
    const context = featureContext();
    const features = await registerFeatures({ ...context, version: ASSET_VERSION });
    featureState.layers = Object.fromEntries(
      attachSceneLayers(scene, { ...context, player, timeline })
        .map((item) => [item.id, item]));
    for (const feature of features) {
      const tab = feature.ui?.tab || `tab-${feature.id}`;
      const button = document.getElementById(feature.ui?.tab_button || `tab-btn-${feature.id}`);
      if (button) button.hidden = !document.getElementById(tab);
    }
    await loadAdapters();
    await loadExamples();
    await loadHistory();
    const list = await api.examples();
    if (list.length) await loadExample(list[0].name);
    loadFlight({
      samples: [], events: [], segments: [], duration: 0,
      script_source: $('#editor-area').value, script_name: currentScriptName(),
    }, {});
    setStatus('Gotowy. Wybierz przykład albo wgraj skrypt i uruchom symulację.');
    applyEditionInfo();
    applyEditionDefaults();
    // tryb automatyczny: po starcie (~1,2 s) zmierz FPS i ewentualnie
    // zaproponuj tryb lekki. W edycji for_potatoes nie ma pomiaru ani pytania.
    if (!edition.lite_default && !isForced() && getMode() === 'auto') {
      setTimeout(() => {
        autoDetect(proposeLite).catch((err) => {
          console.error('perf: pomiar FPS nie powiódł się', err);
        });
      }, 1200);
    }
  } catch (err) {
    console.error(err);
    setStatus(`Błąd inicjalizacji interfejsu: ${err.message}`, 'error');
  }
}

init();


