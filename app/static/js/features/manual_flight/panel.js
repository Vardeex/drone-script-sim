// Panel funkcji "Lot ręczny" (punkt rozszerzeń nr 4).
//
// `registerPanel(ctx)` dostaje od rdzenia: `panels`, `feature`, `scene`
// (DroneScene), `player`, `timeline`, `getLayer(id)`.
//
// Panel prowadzi sesję po stronie serwera (POST /api/manual_flight/*), bo tam
// jest fizyka symulatora - dzięki temu nagranie odtwarza się w skrypcie 1:1.
// Klawiatura -> wychylenia RC (konwencja Tello: lr+ = prawo, yaw+ = w prawo),
// wysyłane co ~100 ms razem z `dt`.

import { el } from '../../js/util.js';

const API = '/api/manual_flight';
//: jak często wysyłamy wychylenia RC [ms] - 10 Hz jak w przykładzie djitellopy
const TICK_MS = 100;
//: mapowanie klawiszy na osie RC (wartość dobiera suwak prędkości)
const KEYS = {
  ArrowUp: ['fb', 1], ArrowDown: ['fb', -1],
  ArrowLeft: ['lr', -1], ArrowRight: ['lr', 1],
  KeyW: ['ud', 1], KeyS: ['ud', -1],
  KeyA: ['yaw', -1], KeyD: ['yaw', 1],
};
const KEY_LABELS = [
  ['↑ / ↓', 'przód / tył'],
  ['← / →', 'lewo / prawo'],
  ['W / S', 'góra / dół'],
  ['A / D', 'obrót w lewo / w prawo'],
];

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch (_) { /* bez JSON */ }
    throw new Error(detail);
  }
  return response.json();
}

const post = (path, payload) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload ?? {}),
});

const PANEL_HTML = `
  <div class="section">
    <h2>Lot ręczny</h2>
    <p class="hint">
      Steruj dronem klawiaturą (jak w przykładzie djitellopy
      <code>manual-control-pygame</code>). Ruch widać na żywo w scenie 3D,
      a przeszkody zgłaszają zbliżenie. Nagranie możesz zapisać jako skrypt.
    </p>
    <div class="mf-row">
      <button type="button" data-mf-start class="primary">▶ Start</button>
      <button type="button" data-mf-land>⏬ Lądowanie</button>
      <button type="button" data-mf-stop class="ghost">■ Zakończ sesję</button>
      <label class="hint mf-speed">Prędkość
        <input type="range" data-mf-speed min="10" max="100" step="5" value="50">
        <span class="mono" data-mf-speed-val>50</span>
      </label>
    </div>
    <div class="mf-status" data-mf-status>
      <span>Pozycja: <b class="mono" data-mf-pos>—</b></span>
      <span>Kurs: <b class="mono" data-mf-yaw>—</b></span>
      <span>Wysokość: <b class="mono" data-mf-z>—</b></span>
      <span>Bateria: <b class="mono" data-mf-battery>—</b></span>
      <span>Odstęp: <b class="mono" data-mf-clearance>—</b></span>
    </div>
    <div class="mf-warning" data-mf-warning hidden></div>
    <div class="mf-keys" data-mf-keys></div>
    <div class="mf-row mf-record">
      <label class="hint"><input type="checkbox" data-mf-record checked> Nagrywaj</label>
      <select data-mf-variant title="Wariant generowanego skryptu"></select>
      <button type="button" data-mf-script>Zapisz jako skrypt</button>
    </div>
    <pre class="mf-script" data-mf-script-out hidden></pre>
    <div class="row" data-mf-script-actions hidden>
      <button type="button" data-mf-copy>Wklej do edytora</button>
      <button type="button" class="ghost" data-mf-download>Pobierz .py</button>
    </div>
    <div class="hint" data-mf-info>Kliknij „Start”, żeby wznieść drona na 80 cm.</div>
  </div>
`;

export function registerPanel({ panels, feature, scene, player, getLayer,
                               getActiveScene } = {}) {
  const state = {
    session: false,
    flying: false,
    speed: 50,
    variant: 'rc',
    pressed: new Set(),
    lastState: null,
    trail: [],
    timer: null,
    lastTick: 0,
    script: '',
    error: null,
  };
  let dom = null;

  const layer = () => {
    if (typeof getLayer !== 'function') return null;
    const found = getLayer(feature?.id);
    return found ? (found.instance || found) : null;
  };

  /** Bieżące wychylenia RC z wciśniętych klawiszy. */
  function currentRc() {
    const rc = { lr: 0, fb: 0, ud: 0, yaw: 0 };
    for (const code of state.pressed) {
      const mapping = KEYS[code];
      if (!mapping) continue;
      rc[mapping[0]] += mapping[1] * state.speed;
    }
    Object.keys(rc).forEach((axis) => {
      rc[axis] = Math.max(-100, Math.min(100, rc[axis]));   // ← i → znoszą się
    });
    return rc;
  }

  function renderKeys() {
    if (!dom) return;
    dom.keys.innerHTML = '';
    for (const [keys, label] of KEY_LABELS) {
      dom.keys.append(el('span', { class: 'mf-key' }, [
        el('kbd', { text: keys }), el('span', { text: label }),
      ]));
    }
  }

  function renderState(next) {
    if (!dom || !next) return;
    state.lastState = next;
    state.flying = Boolean(next.flying);
    dom.pos.textContent = `${next.x.toFixed(0)} / ${next.y.toFixed(0)} cm`;
    dom.yaw.textContent = `${next.yaw.toFixed(0)}°`;
    dom.z.textContent = `${next.z.toFixed(0)} cm`;
    dom.battery.textContent = `${next.battery.toFixed(0)} %`;
    dom.clearance.textContent = next.clearance === null
      ? '—' : `${next.clearance.toFixed(0)} cm`;
    dom.warning.hidden = !next.warning;
    if (next.warning) dom.warning.textContent = next.warning;
    // dron w scenie 3D: cm -> scena, kurs wewnętrzny (CCW+) dla three.js
    scene?.update?.({
      t: next.t, x: next.x, y: next.y, z: next.z,
      yaw: next.yaw_internal ?? 0,
      state: next.flying ? 'airborne' : 'landed',
    });
    if (next.flying) {
      const last = state.trail[state.trail.length - 1];
      if (!last || Math.hypot(last[0] - next.x, last[1] - next.y, last[2] - next.z) > 1.0) {
        state.trail.push([next.x, next.y, next.z]);
        layer()?.setTrail?.(state.trail);
      }
    }
  }

  function setInfo(message, isError = false) {
    if (!dom) return;
    dom.info.textContent = message;
    dom.info.classList.toggle('mf-error', Boolean(isError));
  }

  async function tick() {
    if (!state.session) return;
    const now = performance.now();
    const dt = state.lastTick ? (now - state.lastTick) / 1000 : TICK_MS / 1000;
    state.lastTick = now;
    const rc = currentRc();
    const moving = rc.lr || rc.fb || rc.ud || rc.yaw;
    if (!state.flying && !moving) return;        // na ziemi bez klawiszy nic nie robimy
    try {
      const next = await post('/rc', { ...rc, dt: Math.min(Math.max(dt, 0.01), 0.3) });
      renderState(next);
    } catch (err) {
      state.error = String(err.message || err);
      stopLoop();
      setInfo(`Błąd lotu ręcznego: ${state.error}`, true);
    }
  }

  function startLoop() {
    if (state.timer) return;
    state.lastTick = 0;
    state.timer = window.setInterval(tick, TICK_MS);
  }

  function stopLoop() {
    if (!state.timer) return;
    window.clearInterval(state.timer);
    state.timer = null;
  }

  // ---------------------------------------------------------------- akcje UI
  async function ensureSession() {
    if (state.session) return true;
    player?.pause?.();
    // aktywna scena przeszkód (o ile funkcja „Przeszkody” jest włączona) -
    // dzięki niej ostrzeżenia o zbliżeniu liczą się tak samo jak w analizie lotu
    let activeScene = null;
    try {
      activeScene = typeof getActiveScene === 'function' ? getActiveScene() : null;
    } catch (_) {
      activeScene = null;
    }
    const next = await post('/start', { speed: state.speed, scene: activeScene });
    state.session = true;
    state.trail = [];
    layer()?.setTrail?.([]);
    renderState(next);
    startLoop();
    return true;
  }

  async function onStart() {
    try {
      await ensureSession();
      const next = await post('/takeoff');
      renderState(next);
      setInfo('Dron w powietrzu - steruj klawiaturą (kliknij scenę, jeśli klawisze nie działają).');
    } catch (err) {
      setInfo(`Nie udało się wystartować: ${err.message}`, true);
    }
  }

  async function onLand() {
    try {
      if (!state.session) return;
      const next = await post('/land');
      renderState(next);
      setInfo('Dron wylądował. Możesz wystartować ponownie albo zapisać nagranie jako skrypt.');
    } catch (err) {
      setInfo(`Lądowanie nieudane: ${err.message}`, true);
    }
  }

  async function onStop() {
    stopLoop();
    state.pressed.clear();
    state.session = false;
    try {
      await post('/stop');
    } catch (_) { /* sesja mogła już nie istnieć */ }
    state.trail = [];
    layer()?.setTrail?.([]);
    setInfo('Sesja zakończona. Kliknij „Start”, żeby zacząć nową.');
  }

  async function onGenerate() {
    try {
      const data = await api('/script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ variant: state.variant }),
      });
      state.script = data.source;
      dom.scriptOut.hidden = false;
      dom.scriptOut.textContent = data.source;
      dom.scriptActions.hidden = false;
      setInfo(`Wygenerowano skrypt (${data.label}), ${data.segments} odcinków nagrania.`);
    } catch (err) {
      setInfo(`Nie udało się wygenerować skryptu: ${err.message}`, true);
    }
  }

  function onCopyToEditor() {
    if (!state.script) return;
    const area = document.querySelector('#editor-area');
    if (!area) return;
    area.value = state.script;
    area.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector("button[data-tab='tab-script']")?.click();
    setInfo('Skrypt wklejony do edytora - możesz go uruchomić przyciskiem „Uruchom”.');
  }

  function onDownload() {
    if (!state.script) return;
    const blob = new Blob([state.script], { type: 'text/x-python' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'lot_reczny.py';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  // ------------------------------------------------------------- klawiatura
  function onKeyDown(event) {
    if (!KEYS[event.code] || !state.session) return;
    const tag = (event.target?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    event.preventDefault();
    state.pressed.add(event.code);
  }

  function onKeyUp(event) {
    if (!KEYS[event.code]) return;
    state.pressed.delete(event.code);
  }

  function onBlur() {
    state.pressed.clear();       // okno straciło fokus - nie zostawiaj wciśniętego RC
  }

  function mount(section) {
    if (!section) return;
    section.innerHTML = PANEL_HTML;
    dom = {
      start: section.querySelector('[data-mf-start]'),
      land: section.querySelector('[data-mf-land]'),
      stop: section.querySelector('[data-mf-stop]'),
      speed: section.querySelector('[data-mf-speed]'),
      speedVal: section.querySelector('[data-mf-speed-val]'),
      pos: section.querySelector('[data-mf-pos]'),
      yaw: section.querySelector('[data-mf-yaw]'),
      z: section.querySelector('[data-mf-z]'),
      battery: section.querySelector('[data-mf-battery]'),
      clearance: section.querySelector('[data-mf-clearance]'),
      warning: section.querySelector('[data-mf-warning]'),
      keys: section.querySelector('[data-mf-keys]'),
      record: section.querySelector('[data-mf-record]'),
      variant: section.querySelector('[data-mf-variant]'),
      script: section.querySelector('[data-mf-script]'),
      scriptOut: section.querySelector('[data-mf-script-out]'),
      scriptActions: section.querySelector('[data-mf-script-actions]'),
      copy: section.querySelector('[data-mf-copy]'),
      download: section.querySelector('[data-mf-download]'),
      info: section.querySelector('[data-mf-info]'),
    };
    renderKeys();
    dom.start.addEventListener('click', onStart);
    dom.land.addEventListener('click', onLand);
    dom.stop.addEventListener('click', onStop);
    dom.script.addEventListener('click', onGenerate);
    dom.copy.addEventListener('click', onCopyToEditor);
    dom.download.addEventListener('click', onDownload);
    dom.speed.addEventListener('input', async () => {
      state.speed = Number(dom.speed.value);
      dom.speedVal.textContent = String(state.speed);
      if (state.session) {
        try {
          await post('/speed', { speed: state.speed });
        } catch (_) { /* zmiana lokalna wystarczy */ }
      }
    });
    dom.record.addEventListener('change', async () => {
      if (!state.session) return;
      try {
        await post('/record', { enabled: dom.record.checked });
      } catch (_) { /* nagrywanie po stronie serwera zostaje bez zmian */ }
    });
    // warianty skryptu pobieramy z API (jedno źródło prawdy - backend)
    api('/variants').then((data) => {
      dom.variant.innerHTML = '';
      for (const item of data.variants) {
        dom.variant.append(el('option', { value: item.id, text: item.label }));
      }
      dom.variant.value = state.variant;
    }).catch(() => { /* zostaje domyślny wariant */ });
    dom.variant.addEventListener('change', () => { state.variant = dom.variant.value; });

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', onBlur);
    // diagnostyka i testy przeglądarkowe (stan tylko do odczytu + pomocnicze akcje)
    window.__manualFlight = {
      get state() { return { ...state, pressed: [...state.pressed] }; },
      rc: currentRc,
      press: (code) => state.pressed.add(code),
      release: (code) => state.pressed.delete(code),
      tick,
    };
  }

  panels.register({ mount });
}
