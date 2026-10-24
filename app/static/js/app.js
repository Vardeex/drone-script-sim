// Drone Script Simulator - logika interfejsu (spina scenę, panele i API).
import { $, $$, el, fmt, fmtTime, debounce, legendGradient, plural, STATUS_LABEL } from './util.js';
import { FlightTimeline, Player } from './timeline.js';
import { DroneScene } from './scene.js';
import { api, waitForRun } from './api.js';
import { showTooltip, hideTooltip } from './tooltip.js';
import * as panels from './panels.js';
import { registerFeatures, attachSceneLayers } from './boot.js';
import { renderPlugins } from './plugins_tab.js';

//: wersja modułów funkcji (cache-busting lokalnego serwera statyków)
export const ASSET_VERSION = 'v25';

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
const scene = new DroneScene($('#viewport'));
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
  if (!state.editorDirty && timeline.source) $('#editor-area').value = timeline.source;

  player.pause();
  player.setTime(0);
  updatePlayButton();
  scene.fitView();
  onFrame(0);
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
  $('#editor-area').value = data.source;
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

function historyRow(item) {
  const row = el('div', { class: 'flight-item' });
  row.append(el('div', {}, [
    el('div', { class: 'name', text: item.script_name || item.id }),
    el('div', {
      class: 'meta',
      text: `${(item.created_at || '').replace('T', ' ').slice(0, 19)} · `
        + `${fmtTime(item.duration)} · ${item.events} komend · `
        + `${item.errors || 0} bł. · ${item.warnings || 0} ostr.`,
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
  $('#editor-area').value = text;
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
  $('#camera-select').addEventListener('change', (e) => {
    scene.setCameraMode(e.target.value);
    if (e.target.value !== 'orbit') {
      scene.fitView();
      scene.setCameraMode(e.target.value);
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
    $('#editor-area').value = '';
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
    const tag = document.activeElement?.tagName;
    const typing = ['TEXTAREA', 'INPUT', 'SELECT'].includes(tag);
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runSimulation();
      return;
    }
    if (typing) return;
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
  } catch (err) {
    console.error(err);
    setStatus(`Błąd inicjalizacji interfejsu: ${err.message}`, 'error');
  }
}

init();


