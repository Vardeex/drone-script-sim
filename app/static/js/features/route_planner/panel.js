// Panel funkcji „Planer trasy” (punkt rozszerzeń nr 4).
//
// Rdzeń dostaje obiekt z metodami (patrz `registerPanel` niżej):
//   getRunOptions()  - `{route_planner: {route}}` dopisywane do /api/run,
//   getFindings()    - problemy trasy dla zakładki „Problemy”,
//   getScene()       - trasa do zapisania razem ze sceną (`routes`).
// Trasa jest edytowana w panelu i rysowana w warstwie 3D (scene_layer.js).

import { isLite, onPerfChange } from '../../js/perf.js';

const API = '/api/route_planner';
const MODES = [
  { id: 'simple', label: 'Prosta (djitellopy)' },
  { id: 'smooth', label: 'Płynna (dronemoves) — eksperymentalna' },
];
const HEADINGS = [
  { id: 'track', label: 'po torze' },
  { id: 'fixed', label: 'stały kurs' },
  { id: 'point', label: 'na punkt' },
  { id: 'start', label: 'na start' },
];

/** Stan panelu: trasa w formacie modelu (``dronesim-route``). */
export const store = {
  route: blankRoute(),
  selection: null,
  info: null,
  preview: null,
  validation: null,
  placing: false,
  dragging: true,
  scene: null,
  layer: null,
  ctx: null,
  //: czy rysować linię planu (null = decyduje tryb wydajności)
  showPreview: null,
};

function blankRoute() {
  return {
    format: 'dronesim-route',
    version: 1,
    mode: 'simple',
    default_speed: 50,
    start_yaw_deg: 0,
    return_home: false,
    points: [],
  };
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Błąd ${response.status}`);
  }
  return data;
}

function status(text, kind = '') {
  const el = document.getElementById('route-status');
  if (!el) return;
  el.textContent = text;
  el.dataset.kind = kind;
}

function el(id) {
  return document.getElementById(id);
}

// ------------------------------------------------------------- edycja punktów
/** Punkt trasy: pozycja w cm i opis nosa (format modelu). */
function makePoint(x, y, z) {
  return { x: Math.round(x), y: Math.round(y), z: Math.round(z),
           heading: 'track', yaw_deg: 0, hover_s: 0, speed: null };
}

function addPoint(x, y, z) {
  store.route.points.push(makePoint(x, y, z));
  store.selection = store.route.points.length - 1;
  changed();
}

function removePoint(index) {
  store.route.points.splice(index, 1);
  if (store.selection !== null && store.selection >= store.route.points.length) {
    store.selection = store.route.points.length ? store.route.points.length - 1 : null;
  }
  changed();
}

function movePoint(index, delta) {
  const target = index + delta;
  const points = store.route.points;
  if (target < 0 || target >= points.length) return;
  const [point] = points.splice(index, 1);
  points.splice(target, 0, point);
  store.selection = target;
  changed();
}

function updatePoint(index, patch) {
  const point = store.route.points[index];
  if (!point) return;
  Object.assign(point, patch);
  // nie przerysowujemy listy: użytkownik właśnie edytuje pole i utraciłby fokus
  if (store.layer) store.layer.setRoute(store.route);
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, previewDelay());
}

/** Opóźnienie podglądu: w trybie lekkim 300 ms (mniej zapytań przy przeciąganiu). */
function previewDelay() {
  return isLite() ? 300 : 220;
}

/** Czy rysować zieloną linię planu (w trybie lekkim domyślnie nie). */
function showPlanLine() {
  if (store.showPreview !== null) return store.showPreview;
  return !isLite();
}

/** Po każdej zmianie trasy: warstwa 3D, lista, podgląd (debounce). */
let previewTimer = null;
function changed() {
  if (store.layer) {
    store.layer.setRoute(store.route);
    store.layer.setSelection(store.selection);
  }
  renderPoints();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, previewDelay());
}

// --------------------------------------------------------------- podgląd
/**
 * Stan podglądu: nowe żądanie unieważnia starsze odpowiedzi (licznik).
 * Bez tego przy dwóch szybkich zmianach trasy starsza odpowiedź mogła
 * nadpisać nowszą i UI pokazywał nieaktualne „Punkty: N”.
 */
let previewRequest = 0;

async function refreshPreview() {
  if (!store.route.points.length) {
    previewRequest += 1;                 // anuluj ewentualne żądanie w locie
    store.preview = null;
    store.validation = null;
    if (store.layer) store.layer.setPreview([]);
    renderStats(null);
    renderProblems([]);
    updateWarning();
    return;
  }
  const request = ++previewRequest;
  renderStats(null, { pending: true });  // „Liczę podgląd…” zamiast „Brak podglądu.”
  const body = JSON.stringify({ route: store.route, scene: store.scene });
  try {
    const [preview, validation] = await Promise.all([
      api('/preview', { method: 'POST', body }),
      api('/validate', { method: 'POST', body }),
    ]);
    if (request !== previewRequest) return;   // przyszła nowsza odpowiedź
    store.preview = preview;
    store.validation = validation;
    if (store.layer && preview.points) {
      store.layer.setPreview(showPlanLine() ? preview.points : []);
    }
    renderStats(preview);
    renderProblems(validation.problems || []);
    updateWarning();
  } catch (err) {
    if (request !== previewRequest) return;
    renderStats(null, { error: String(err.message || err) });
    status(String(err.message || err), 'error');
  }
}


// --------------------------------------------------------------- render
function renderPoints() {
  const list = el('route-points');
  if (!list) return;
  list.innerHTML = '';
  if (!store.route.points.length) {
    const empty = document.createElement('div');
    empty.className = 'route-empty';
    empty.textContent = 'Brak punktów. Kliknij „Dodaj punkt” (albo włącz dodawanie '
      + 'klikiem) i wskaż miejsce na podłożu.';
    list.append(empty);
    return;
  }
  store.route.points.forEach((point, index) => {
    const row = document.createElement('div');
    row.className = 'route-point' + (store.selection === index ? ' selected' : '');
    row.dataset.index = String(index);

    const idx = document.createElement('span');
    idx.className = 'idx';
    idx.textContent = String(index + 1);
    idx.title = 'Wybierz punkt';
    idx.addEventListener('click', () => select(index));
    row.append(idx);

    for (const axis of ['x', 'y', 'z']) {
      const input = document.createElement('input');
      input.type = 'number';
      input.step = '1';
      input.value = String(Math.round(point[axis]));
      input.dataset.axis = axis;
      input.title = `${axis.toUpperCase()} [cm]`;
      input.addEventListener('change', () => {
        updatePoint(index, { [axis]: Number(input.value) || 0 });
      });
      input.addEventListener('focus', () => select(index));
      row.append(input);
    }

    const heading = document.createElement('select');
    heading.title = 'Kurs nosa w punkcie';
    for (const option of HEADINGS) {
      const opt = document.createElement('option');
      opt.value = option.id;
      opt.textContent = option.label;
      heading.append(opt);
    }
    heading.value = point.heading || 'track';
    heading.addEventListener('change', () => updatePoint(index, { heading: heading.value }));
    row.append(heading);

    const actions = document.createElement('span');
    actions.className = 'actions';
    const buttons = [['↑', 'Przesuń w górę', () => movePoint(index, -1)],
                     ['↓', 'Przesuń w dół', () => movePoint(index, 1)],
                     ['✚', 'Wstaw punkt za tym', () => insertAfter(index)],
                     ['✕', 'Usuń punkt', () => removePoint(index)]];
    for (const [glyph, title, handler] of buttons) {
      const button = document.createElement('button');
      button.className = 'ghost';
      button.textContent = glyph;
      button.title = title;
      button.addEventListener('click', handler);
      actions.append(button);
    }
    row.append(actions);
    list.append(row);
  });
}

function insertAfter(index) {
  const base = store.route.points[index] || { x: 0, y: 0, z: 100 };
  store.route.points.splice(index + 1, 0, makePoint(base.x + 100, base.y, base.z));
  store.selection = index + 1;
  changed();
}

function select(index) {
  store.selection = index;
  if (store.layer) store.layer.setSelection(index);
  renderPoints();
}

function renderStats(preview, state = {}) {
  const box = el('route-stats');
  if (!box) return;
  if (state.pending) {
    box.innerHTML = '<span class="route-pending">Liczę podgląd…</span>';
    return;
  }
  if (state.error) {
    box.innerHTML = `<span class="route-pending error">Nie udało się policzyć podglądu: `
      + `${state.error}</span>`;
    return;
  }
  if (!preview) {
    box.innerHTML = '<span>Brak podglądu.</span>';
    return;
  }
  const stats = preview.stats || preview;
  const parts = [
    ['Dystans', `${Math.round(stats.distance_cm || 0)} cm`],
    ['Czas', `${(stats.eta_s || stats.duration_s || 0).toFixed(1)} s`],
    ['Bateria', `${(stats.battery_pct || 0).toFixed(1)} %`],
    ['Punkty', `${store.route.points.length}`],
  ];
  box.innerHTML = parts.map(([k, v]) => `<span>${k}: <b>${v}</b></span>`).join('');
}

function renderProblems(problems) {
  const box = el('route-problems');
  if (!box) return;
  box.innerHTML = '';
  for (const problem of problems) {
    const item = document.createElement('li');
    item.className = problem.level === 'error' ? 'error' : 'warning';
    item.textContent = problem.message;
    box.append(item);
  }
}

/** Ostrzeżenie o odchyleniu trybu „płynna” (KNOWN_ISSUES KI-1) - zamiast blokady. */
function updateWarning() {
  const box = el('route-warning');
  if (!box) return;
  const validation = store.validation;
  const deviation = validation?.smooth_deviation_cm;
  if (store.route.mode === 'smooth' && deviation != null && deviation > 15) {
    box.hidden = false;
    box.textContent = `tryb płynny: odchylenie do ${Math.round(deviation)} cm od punktów `
      + '(eksperymentalny — patrz KNOWN_ISSUES.md)';
  } else {
    box.hidden = true;
    box.textContent = '';
  }
}


// --------------------------------------------------------------- akcje
let lastCode = '';

async function generateCode(run) {
  if (!store.route.points.length) {
    status('Trasa jest pusta - dodaj przynajmniej jeden punkt.', 'error');
    return;
  }
  try {
    const data = await api('/code', {
      method: 'POST',
      body: JSON.stringify({ route: store.route, scene: store.scene,
                             mode: store.route.mode }),
    });
    lastCode = data.code;
    const codeBox = el('route-code');
    if (codeBox) codeBox.value = data.code;
    const errors = (data.problems || []).filter((p) => p.level === 'error');
    if (errors.length) {
      status(`Trasa ma błędy: ${errors[0].message}`, 'error');
      return;
    }
    status(`Wygenerowano kod (${data.mode === 'smooth' ? 'płynna' : 'prosta'}, `
      + `${data.code.split('\n').length} linii).`, 'ok');
    if (run) {
      const editor = el('code');
      if (editor) {
        editor.value = data.code;
        editor.dispatchEvent(new Event('input', { bubbles: true }));
      }
      el('btn-run')?.click();
      status('Uruchomiono wygenerowany skrypt w symulatorze.', 'ok');
    }
  } catch (err) {
    status(String(err.message || err), 'error');
  }
}

async function copyCode() {
  if (!lastCode) await generateCode(false);
  if (!lastCode) return;
  try {
    await navigator.clipboard.writeText(lastCode);
    status('Kod skopiowany do schowka.', 'ok');
  } catch {
    const codeBox = el('route-code');
    codeBox?.select();
    status('Schowek niedostępny - kod zaznaczony, użyj Ctrl+C.', '');
  }
}

function downloadCode() {
  if (!lastCode) {
    status('Najpierw wygeneruj kod.', 'error');
    return;
  }
  const blob = new Blob([lastCode], { type: 'text/x-python;charset=utf-8' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `trasa_${store.route.mode}.py`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  status('Pobrano plik .py.', 'ok');
}

async function loadFromScript() {
  const editor = el('code');
  const source = editor ? editor.value : '';
  if (!source.trim()) {
    status('Edytor skryptu jest pusty.', 'error');
    return;
  }
  try {
    const data = await api('/load', { method: 'POST', body: JSON.stringify({ source }) });
    store.route = data.route;
    store.selection = store.route.points.length ? 0 : null;
    syncOptions();
    changed();
    status(`Wczytano trasę: ${store.route.points.length} pkt.`, 'ok');
  } catch (err) {
    status(String(err.message || err), 'error');
  }
}

function syncOptions() {
  const mode = el('route-mode');
  if (mode) mode.value = store.route.mode || 'simple';
  const speed = el('route-speed');
  if (speed) speed.value = String(store.route.default_speed ?? 50);
  const yaw = el('route-yaw');
  if (yaw) yaw.value = String(store.route.start_yaw_deg ?? 0);
  const home = el('route-return');
  if (home) home.checked = Boolean(store.route.return_home);
}

function setMode(mode) {
  store.route.mode = mode;
  status(mode === 'smooth'
    ? 'Tryb „płynna” jest eksperymentalny (patrz KNOWN_ISSUES.md).'
    : 'Tryb „prosta” - domyślny.', '');
  updateWarning();
  const warnMode = el('route-mode-hint');
  if (warnMode) {
    warnMode.hidden = mode !== 'smooth';
  }
}


// --------------------------------------------------------------- szablon
const MODE_OPTIONS = MODES.map((m) => `<option value="${m.id}">${m.label}</option>`).join('');

function template() {
  return `
<div class="section" id="route-panel">
  <div class="row between" style="margin-bottom:6px">
    <h2 style="margin:0">Planer trasy</h2>
    <span class="hint" id="route-status"></span>
  </div>

  <div class="route-toolbar">
    <button id="route-add" class="ghost" title="Dodaj punkt na końcu trasy">✚ Dodaj punkt</button>
    <button id="route-place" class="ghost toggle" title="Dodawanie punktów klikiem na podłożu">🖱 Klik na podłożu</button>
    <button id="route-drag" class="ghost toggle on" title="Przeciąganie punktów (Shift = wysokość)">✥ Przeciąganie</button>
    <button id="route-clear" class="ghost" title="Usuń wszystkie punkty">🗑 Wyczyść</button>
  </div>

  <div class="route-options">
    <label for="route-mode">Tryb</label>
    <select id="route-mode" title="Tryb generowania skryptu">${MODE_OPTIONS}</select>
    <label for="route-speed">Prędkość [cm/s]</label>
    <input id="route-speed" type="number" min="10" max="100" step="5" value="50">
    <label for="route-yaw">Kurs startowy [°]</label>
    <input id="route-yaw" type="number" min="-180" max="360" step="15" value="0">
    <label for="route-return">Wróć do startu</label>
    <input id="route-return" type="checkbox">
    <label for="route-preview" title="Zielona przerywana linia planu na scenie 3D (w trybie lekkim domyślnie wyłączona)">Linia planu</label>
    <input id="route-preview" type="checkbox" checked>
  </div>
  <div class="route-warning" id="route-mode-hint" hidden>
    Tryb „płynna” jest <b>eksperymentalny</b>: korzysta z biblioteki dronemoves
    i może odstawać od punktów (patrz KNOWN_ISSUES.md).
  </div>
  <div class="route-warning" id="route-warning" hidden></div>

  <div class="route-points" id="route-points"></div>
  <div class="route-stats" id="route-stats"><span>Brak podglądu.</span></div>
  <ul class="route-problems" id="route-problems"></ul>

  <div class="route-actions">
    <button id="route-generate" class="primary" title="Wygeneruj kod i uruchom w symulatorze">▶ Wygeneruj i uruchom</button>
    <button id="route-preview-code" class="ghost" title="Wygeneruj kod do edytora">⌨ Pokaż kod</button>
    <button id="route-copy" class="ghost" title="Kopiuj wygenerowany kod">📋 Kopiuj kod</button>
    <button id="route-download" class="ghost" title="Pobierz skrypt jako .py">💾 Pobierz .py</button>
    <button id="route-load" class="ghost" title="Wczytaj trasę z bloku w edytorze skryptu">📥 Wczytaj ze skryptu</button>
  </div>
  <textarea id="route-code" spellcheck="false" readonly
            style="width:100%;height:120px;margin-top:6px;display:none"></textarea>
</div>`;
}

function ensurePanel() {
  const tab = el('tab-route');
  if (!tab) return null;
  if (!el('route-panel')) tab.insertAdjacentHTML('afterbegin', template());
  return el('route-panel');
}

function bind() {
  const on = (id, event, handler) => el(id)?.addEventListener(event, handler);
  on('route-add', 'click', () => {
    const points = store.route.points;
    const last = points[points.length - 1];
    addPoint(last ? last.x + 100 : 100, last ? last.y : 0, last ? last.z : 100);
  });
  on('route-clear', 'click', () => {
    store.route.points = [];
    store.selection = null;
    changed();
  });
  on('route-place', 'click', () => togglePlacing());
  on('route-drag', 'click', () => toggleDragging());
  on('route-mode', 'change', (e) => setMode(e.target.value));
  on('route-speed', 'change', (e) => {
    store.route.default_speed = Number(e.target.value) || 50;
    changed();
  });
  on('route-yaw', 'change', (e) => {
    store.route.start_yaw_deg = Number(e.target.value) || 0;
    changed();
  });
  on('route-return', 'change', (e) => {
    store.route.return_home = e.target.checked;
    changed();
  });
  // linia planu: w trybie lekkim domyślnie wyłączona, ale można ją włączyć
  const previewBox = el('route-preview');
  if (previewBox) {
    previewBox.checked = showPlanLine();
    on('route-preview', 'change', (e) => {
      store.showPreview = e.target.checked;
      if (store.preview?.points && store.layer) {
        store.layer.setPreview(e.target.checked ? store.preview.points : []);
      }
    });
  }
  // zmiana trybu wydajności: linia planu wraca do domyślnej widoczności
  onPerfChange(() => {
    if (store.showPreview === null && previewBox) previewBox.checked = showPlanLine();
  });
  on('route-generate', 'click', () => generateCode(true));
  on('route-preview-code', 'click', async () => {
    await generateCode(false);
    const box = el('route-code');
    if (box) box.style.display = 'block';
  });
  on('route-copy', 'click', copyCode);
  on('route-download', 'click', downloadCode);
  on('route-load', 'click', loadFromScript);
  setMode(store.route.mode);
}

/**
 * Podłącz warstwę 3D. Panel powstaje przed warstwą sceny (rdzeń rejestruje
 * panele, potem dokłada warstwy), więc sprawdzamy też kilka kolejnych klatek.
 */
function attachLayer() {
  const ctx = store.ctx || {};
  const id = ctx.feature?.id || 'route_planner';
  const status = typeof ctx.getLayer === 'function' ? ctx.getLayer(id) : null;
  store.layer = status ? (status.instance || status) : null;
  if (store.layer) {
    store.layer.setRoute(store.route);
    toggleDragging(store.dragging);
    togglePlacing(store.placing);
    return true;
  }
  return false;
}

function waitForLayer(attempts = 40) {
  if (attachLayer()) return;
  if (attempts <= 0) return;
  setTimeout(() => waitForLayer(attempts - 1), 100);
}

function togglePlacing(force) {
  store.placing = force ?? !store.placing;
  el('route-place')?.classList.toggle('on', store.placing);
  store.layer?.setPlaceMode(store.placing, { onAdd: (p) => addPoint(p.x, p.y, p.z) });
  status(store.placing ? 'Kliknij na podłożu, aby dodać punkt.' : '', '');
}

function toggleDragging(force) {
  store.dragging = force ?? !store.dragging;
  el('route-drag')?.classList.toggle('on', store.dragging);
  store.layer?.setDragMode(store.dragging, {
    onSelect: (index) => select(index),
    onMove: (index, patch) => {
      const point = store.route.points[index];
      if (!point) return;
      if (patch.dz !== undefined) {
        point.z = Math.max(20, Math.round(point.z + patch.dz));
      } else {
        point.x = Math.round(patch.x);
        point.y = Math.round(patch.y);
      }
      store.layer.setRoute(store.route);
      store.layer.setSelection(index);
      renderPoints();
    },
  });
}

export function registerPanel(context = {}) {
  store.ctx = context;
  ensurePanel();
  bind();
  waitForLayer();
  changed();
  return {
    getRunOptions: () => ({ route_planner: { route: store.route } }),
    getFindings: () => (store.validation?.problems || []).map((p) => ({
      level: p.level === 'error' ? 'collision' : 'warning',
      message: p.message,
    })),
    getScene: () => (store.route.points.length ? { routes: [store.route] } : {}),
    getRoute: () => store.route,
    setRoute: (route) => {
      store.route = route || blankRoute();
      store.selection = store.route.points.length ? 0 : null;
      syncOptions();
      changed();
    },
  };
}
