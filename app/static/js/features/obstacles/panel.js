// Panel funkcji "Przeszkody 3D" (punkt rozszerzeń nr 4).
//
// `registerPanel(ctx)` dostaje od rdzenia: `panels` (rejestr paneli UI),
// `feature` (manifest), `getActiveScene`/`setActiveScene` (aktywna scena),
// `onCollisionStop` (zatrzymanie odtwarzania przy kolizji) i `scene` (DroneScene).
// Panel nie zna wnętrza rdzenia poza tymi punktami wejścia.

// Ścieżki liczone od adresu serwowanego modułu (/static/features/<id>/panel.js),
// nie od położenia pliku w repo - dlatego '../../js/' zamiast '../../../'.
import { $, el, fmt } from '../../js/util.js';


const KIND_LABELS = {
  box: 'prostopadłościan', cylinder: 'walec', gate: 'bramka', plane: 'płaszczyzna',
  mission_pad: 'mata (Mission Pad)',
};
const PRESETS = {
  box: { size: [20, 200, 200], name: 'ściana' },
  cylinder: { size: [30, 30, 150], name: 'słup' },
  gate: { size: [120, 5, 120], opening: [90, 90], thickness: 5, name: 'bramka' },
  plane: { size: [400, 400, 5], thickness: 5, name: 'sufit' },
  mission_pad: { size: [30, 30, 1], name: 'mata' },
};
const STORAGE_KEY = 'dronesim.obstacles.settings';
//: nazwa ostatnio wybranej sceny (localStorage) - po restarcie wracamy do niej
const SCENE_KEY = 'dronesim.obstacles.scene';

async function api(path, options = {}) {
  const response = await fetch(`/api/obstacles${path}`, options);
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

const postJson = (path, payload) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

let seq = 0;
function newId(kind) {
  seq += 1;
  return `${kind}-${Date.now().toString(36).slice(-4)}${seq}`;
}

function loadSettings() {
  try {
    return { margin: 20, view: 'ghost', labels: true, stopOnCollision: false,
      ...JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') };
  } catch (_) {
    return { margin: 20, view: 'ghost', labels: true, stopOnCollision: false };
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (_) { /* prywatny tryb przeglądarki */ }
}

/** Nazwa ostatnio wybranej sceny (``null`` = brak zapamiętanej / brak storage). */
function loadScenePreference() {
  try {
    return localStorage.getItem(SCENE_KEY) || null;
  } catch (_) {
    return null;                 // prywatny tryb: po prostu pusta scena
  }
}

function saveScenePreference(name) {
  try {
    if (name) localStorage.setItem(SCENE_KEY, name);
    else localStorage.removeItem(SCENE_KEY);
  } catch (_) { /* brak localStorage nie jest błędem */ }
}

function sceneDistance(obstacle) {
  const [x, y, z] = obstacle.position || [0, 0, 0];
  return Math.hypot(x, y, z);
}

function clampSize(obstacle) {
  for (const key of ['dx', 'dy', 'dz']) {
    const index = { dx: 0, dy: 1, dz: 2 }[key];
    if (obstacle.size[index] < 1) obstacle.size[index] = 1;
  }
}

/**
 * Zarejestruj panel przeszkód.
 * @param {{panels: object, feature: object, getActiveScene: Function,
 *          setActiveScene: Function, onCollisionStop: Function, scene: object}} ctx
 */
export function registerPanel(ctx) {
  const settings = loadSettings();
  const store = {
    scene: null,
    selectedId: null,
    name: '',
    dirty: false,
    isUserScene: false,
    list: [],
    findings: [],
  };

  function notifySaved() {
    store.dirty = false;
    renderHeader();
  }

  /** Instancja warstwy 3D funkcji (rdzeń trzyma `{ id, instance, factory }`). */
  function getLayer() {
    if (typeof ctx.getLayer !== "function") return null;
    const status = ctx.getLayer(ctx.feature?.id);
    if (!status) return null;
    return status.instance || status;
  }

  function markDirty() {
    store.dirty = true;
    renderHeader();
  }

  // ------------------------------------------------------- edycja przeszkód
  function addObstacle(kind) {
    const preset = PRESETS[kind] || PRESETS.box;
    const obstacle = {
      id: newId(kind),
      kind,
      name: `${preset.name} ${store.scene.obstacles.filter((o) => o.kind === kind).length + 1}`,
      position: [0, 0, kind === 'plane' ? 250 : kind === 'mission_pad' ? 0 : 80],
      size: [...preset.size],
      yaw_deg: 0,
    };
    if (kind === 'mission_pad') {
      // kolejny wolny numer maty 1-8 (po zajętych); przy 8-matowej scenie powtarza
      const used = new Set(store.scene.obstacles
        .filter((o) => o.kind === 'mission_pad').map((o) => o.pad_id));
      obstacle.pad_id = [1, 2, 3, 4, 5, 6, 7, 8].find((n) => !used.has(n)) || 1;
      obstacle.name = `mata ${obstacle.pad_id}`;
    }
    if (preset.opening) obstacle.opening = [...preset.opening];
    if (preset.thickness) obstacle.thickness = preset.thickness;
    store.scene.obstacles.push(obstacle);
    store.selectedId = obstacle.id;
    markDirty();
    applyToScene();
  }

  function duplicateObstacle() {
    const source = selected();
    if (!source) return;
    const copy = JSON.parse(JSON.stringify(source));
    copy.id = newId(source.kind);
    copy.name = `${source.name} (kopia)`;
    copy.position = [source.position[0] + 30, source.position[1] + 30, source.position[2]];
    store.scene.obstacles.push(copy);
    store.selectedId = copy.id;
    markDirty();
    applyToScene();
  }

  function removeObstacle() {
    const source = selected();
    if (!source) return;
    store.scene.obstacles = store.scene.obstacles.filter((o) => o.id !== source.id);
    store.selectedId = null;
    markDirty();
    applyToScene();
  }

  function selected() {
    return store.scene?.obstacles.find((o) => o.id === store.selectedId) || null;
  }

  function renderEditor() {
    const box = $('#obs-editor');
    if (!box) return;
    box.innerHTML = '';
    const obstacle = selected();
    if (!obstacle) {
      box.append(el('div', { class: 'hint',
        text: 'Wybierz przeszkodę na liście lub kliknij ją w scenie 3D.' }));
      return;
    }
    const distance = sceneDistance(obstacle);
    const nameInput = el('input', { type: 'text', value: obstacle.name });
    nameInput.addEventListener('change', () => {
      obstacle.name = nameInput.value.trim() || KIND_LABELS[obstacle.kind];
      markDirty();
      applyToScene();
    });
    box.append(el('label', { class: 'obs-field wide' }, [
      el('span', { text: `Nazwa · ${KIND_LABELS[obstacle.kind] || obstacle.kind}` }), nameInput,
    ]));

    const position = el('div', { class: 'obs-grid3' }, [
      numberField('X', obstacle.position[0], (v) => { obstacle.position[0] = v; }),
      numberField('Y', obstacle.position[1], (v) => { obstacle.position[1] = v; }),
      numberField('Z', obstacle.position[2], (v) => { obstacle.position[2] = v; }, { min: 0 }),
    ]);
    box.append(position);

    const sizeLabels = obstacle.kind === 'cylinder' ? ['średnica', 'średnica', 'wysokość']
      : ['szer. (X)', 'gł. (Y)', 'wys. (Z)'];
    const size = el('div', { class: 'obs-grid3' }, [
      numberField(sizeLabels[0], obstacle.size[0],
        (v) => { obstacle.size[0] = Math.max(1, v); if (obstacle.kind === 'cylinder') obstacle.size[1] = Math.max(1, v); }, { min: 1 }),
      numberField(sizeLabels[1], obstacle.size[1],
        (v) => { obstacle.size[1] = Math.max(1, v); if (obstacle.kind === 'cylinder') obstacle.size[0] = Math.max(1, v); }, { min: 1 }),
      numberField(sizeLabels[2], obstacle.size[2], (v) => { obstacle.size[2] = Math.max(1, v); }, { min: 1 }),
    ]);
    box.append(size);

    if (obstacle.kind === 'gate') {
      obstacle.opening = obstacle.opening || [60, 60];
      box.append(el('div', { class: 'obs-grid3' }, [
        numberField('otwór X', obstacle.opening[0],
          (v) => { obstacle.opening[0] = Math.max(1, v); }, { min: 1 }),
        numberField('otwór Z', obstacle.opening[1],
          (v) => { obstacle.opening[1] = Math.max(1, v); }, { min: 1 }),
        numberField('grubość', obstacle.thickness || 5,
          (v) => { obstacle.thickness = Math.max(1, v); }, { min: 1 }),
      ]));
    }

    if (obstacle.kind === 'mission_pad') {
      // numer maty = numer kodu, który czyta Tello EDU (m1-m8)
      const padInput = el('input', { type: 'number', min: '1', max: '8', step: '1',
        value: String(obstacle.pad_id || 1) });
      padInput.addEventListener('change', () => {
        const value = Math.min(8, Math.max(1, Math.round(Number(padInput.value) || 1)));
        padInput.value = String(value);
        obstacle.pad_id = value;
        markDirty();
        applyToScene();
      });
      box.append(el('label', { class: 'obs-field wide' }, [
        el('span', { text: 'numer maty (1-8)' }), padInput,
      ]));
      box.append(el('div', { class: 'hint',
        text: 'Dron widzi matę z wysokości 30-120 cm, gdy jest nie dalej niż 30 cm od jej środka.' }));
    }

    const yawInput = el('input', { type: 'range', min: '0', max: '359', step: '1',
      value: String(Math.round(obstacle.yaw_deg || 0)) });
    const yawValue = el('span', { class: 'mono', text: `${fmt(obstacle.yaw_deg || 0, 0)}°` });
    yawInput.addEventListener('input', () => {
      obstacle.yaw_deg = Number(yawInput.value);
      yawValue.textContent = `${fmt(obstacle.yaw_deg, 0)}°`;
      const layer = getLayer(); if (layer) layer.setSelection(store.selectedId);
      markDirty();
    });
    yawInput.addEventListener('change', () => applyToScene());
    box.append(el('label', { class: 'obs-field wide' }, [
      el('span', { text: 'Obrót (0° = dłuższy bok wzdłuż X, + = w prawo)' }), yawInput, yawValue,
    ]));

    box.append(el('div', { class: 'obs-info' }, [
      el('span', { text: `Wymiary: ${fmt(obstacle.size[0], 0)} × ${fmt(obstacle.size[1], 0)}`
        + ` × ${fmt(obstacle.size[2], 0)} cm` }),
      el('span', { text: `Środek: ${fmt(obstacle.position[0], 0)} / ${fmt(obstacle.position[1], 0)}`
        + ` / ${fmt(obstacle.position[2], 0)} cm` }),
      el('span', { class: 'accent', text: `Odległość od startu: ${fmt(distance, 0)} cm` }),
      el('span', { class: 'hint', text: 'Kursor nad wartością = podpowiedź; '
        + 'przeciąganie w scenie (tryb Edycja) przesuwa przeszkodę po podłożu.' }),
    ]));

    box.append(el('div', { class: 'row', style: 'margin-top:8px' }, [
      el('button', { class: 'ghost', text: '⧉ Duplikuj', onclick: duplicateObstacle }),
      el('button', { class: 'ghost', text: '🗑 Usuń', onclick: removeObstacle }),
      el('button', { class: 'ghost', text: '⤓ Na środek ramy', title: 'Ustaw pozycję (0, 0)',
        onclick: () => {
          obstacle.position[0] = 0;
          obstacle.position[1] = 0;
          markDirty();
          applyToScene();
        } }),
    ]));
  }

  function setStatus(text, kind = '') {
    const bar = $('#obs-status');
    if (!bar) return;
    bar.textContent = text;
    bar.className = `hint ${kind}`;
  }

  function renderList() {
    const box = $('#obs-list');
    if (!box) return;
    box.innerHTML = '';
    const obstacles = store.scene?.obstacles || [];
    if (!obstacles.length) {
      box.append(el('div', { class: 'empty', text: 'Scena jest pusta - dodaj przeszkodę.' }));
      return;
    }
    for (const obstacle of obstacles) {
      const row = el('div', {
        class: `obs-item${obstacle.id === store.selectedId ? ' active' : ''}`,
        onclick: () => selectObstacle(obstacle.id),
        title: `${KIND_LABELS[obstacle.kind] || obstacle.kind} · `
          + `${fmt(sceneDistance(obstacle), 0)} cm od startu`,
      }, [
        el('span', { class: `kind ${obstacle.kind}`, text: obstacle.kind }),
        el('span', { class: 'name', text: obstacle.name }),
        el('span', { class: 'meta', text: `${fmt(sceneDistance(obstacle), 0)} cm` }),
      ]);
      box.append(row);
    }
  }

  function selectObstacle(id) {
    store.selectedId = store.selectedId === id ? null : id;
    const layer = getLayer(); if (layer) layer.setSelection(store.selectedId);
    renderList();
    renderEditor();
  }

  function numberField(label, value, onChange, { min = null, step = 1, unit = 'cm' } = {}) {
    const input = el('input', {
      type: 'number', value: String(Number(value).toFixed(2)),
      step: String(step), title: `${label} (${unit})`,
    });
    if (min !== null) input.min = String(min);
    input.addEventListener('change', () => {
      const parsed = Number(input.value);
      onChange(Number.isFinite(parsed) ? parsed : 0);
      markDirty();
      applyToScene();
    });
    return el('label', { class: 'obs-field' }, [
      el('span', { text: label }), input,
    ]);
  }
  function applyToScene() {
    syncLayer();
    renderList();
    renderEditor();
    renderHeader();
    ctx.setActiveScene?.(store.scene);
  }

  /** Narysuj bieżącą scenę w warstwie 3D (jeśli już istnieje). */
  function syncLayer() {
    const view = getLayer();
    if (!view) return;
    view.setScene(store.scene);
    view.setSelection(store.selectedId);
    view.setViewMode(settings.view);
    view.setLabels(settings.labels);
  }

  function renderHeader() {
    const title = document.querySelector('#obs-title');
    if (title) title.textContent = store.scene?.name || 'Nowa scena';
    const badge = document.querySelector('#obs-dirty');
    if (badge) badge.hidden = !store.dirty;
    const path = document.querySelector('#obs-path');
    if (path) {
      path.textContent = store.isUserScene ? 'scena użytkownika (scenes/user)'
        : (store.name ? 'scena przykładowa (scenes)' : 'scena robocza');
    }
  }

  // ------------------------------------------------------------ lista scen
  async function refreshScenes() {
    try {
      store.list = await api('/scenes');
    } catch (err) {
      store.list = [];
      setStatus(`Nie udało się pobrać scen: ${err.message}`, 'error');
    }
    renderSceneList();
  }

  function renderSceneList() {
    const box = $('#obs-scene-list');
    if (!box) return;
    box.innerHTML = '';
    const groups = [
      ['Sceny przykładowe', store.list.filter((s) => !s.user)],
      ['Moje sceny', store.list.filter((s) => s.user)],
    ];
    for (const [label, items] of groups) {
      box.append(el('div', { class: 'obs-group', text: label }));
      if (!items.length) {
        box.append(el('div', { class: 'hint', text: label.startsWith('Moje')
          ? 'Brak zapisanych scen.' : 'Brak scen przykładowych.' }));
        continue;
      }
      for (const item of items) {
        const row = el('button', {
          class: `obs-scene${item.name === store.name ? ' active' : ''}`,
          title: item.description || item.display_name,
          onclick: () => loadScene(item.name),
        }, [
          el('span', { class: 'name', text: item.display_name || item.name }),
          el('span', { class: 'meta', text: `${item.obstacles} przeszk. · ${item.gates} bram.` }),
        ]);
        if (item.user) {
          row.append(el('span', {
            class: 'del', title: 'Usuń scenę', text: '🗑',
            onclick: (event) => {
              event.stopPropagation();
              deleteScene(item.name);
            },
          }));
        }
        box.append(row);
      }
    }
  }

  async function loadScene(name) {
    try {
      const scene = await api(`/scenes/${encodeURIComponent(name)}`);
      store.scene = { name: scene.name, description: scene.description || '',
        room: scene.room || null, obstacles: scene.obstacles || [] };
      store.name = name;
      store.isUserScene = Boolean(store.list.find((s) => s.name === name && s.user));
      store.selectedId = null;
      saveScenePreference(name);        // po restarcie wracamy do tej sceny
      notifySaved();
      applyToScene();
      renderSceneList();
      setStatus(`Wczytano scenę „${scene.name}”.`, 'ok');
    } catch (err) {
      setStatus(`Nie udało się wczytać sceny: ${err.message}`, 'error');
    }
  }

  async function saveScene(asName = null) {
    const name = (asName || store.name || store.scene?.name || 'nowa-scena').trim();
    try {
      const result = await postJson(`/scenes/${encodeURIComponent(name)}`, {
        scene: store.scene,
        overwrite: true,
      });
      store.name = result.name;
      store.isUserScene = true;
      store.scene.name = result.scene.name;
      saveScenePreference(result.name);
      notifySaved();
      await refreshScenes();
      renderList();
      setStatus(`Zapisano scenę „${result.scene.name}” (scenes/user/${result.name}.json).`, 'ok');
    } catch (err) {
      setStatus(`Nie udało się zapisać sceny: ${err.message}`, 'error');
    }
  }

  async function deleteScene(name) {
    if (!window.confirm(`Usunąć scenę „${name}”?`)) return;
    try {
      await api(`/scenes/${encodeURIComponent(name)}`, { method: 'DELETE' });
      if (store.name === name) {
        store.name = '';
        store.isUserScene = false;
        markDirty();
      }
      if (loadScenePreference() === name) saveScenePreference(null);
      await refreshScenes();
      setStatus(`Usunięto scenę „${name}”.`, 'ok');
    } catch (err) {
      setStatus(`Nie udało się usunąć sceny: ${err.message}`, 'error');
    }
  }

  async function newScene() {
    try {
      const scene = await api('/scene/empty', { method: 'POST' });
      store.scene = scene;
      store.name = '';
      store.isUserScene = false;
      store.selectedId = null;
      saveScenePreference(null);        // „Nowa scena” = pusta, także po restarcie
      notifySaved();
      applyToScene();
      setStatus('Nowa pusta scena - dodaj przeszkody.', '');
    } catch (err) {
      setStatus(`Nie udało się utworzyć sceny: ${err.message}`, 'error');
    }
  }

  // ------------------------------------------------- lista problemów (wynik)
  function renderFindings(report) {
    store.findings = report?.findings || [];
    const layer = getLayer(); if (layer) layer.setFindings(store.findings);
    const summary = $('#obs-summary');
    if (summary) {
      summary.innerHTML = '';
      if (report) {
        const s = report.stats || {};
        const minText = s.min_distance_cm === null || s.min_distance_cm === undefined
          ? '—' : `${fmt(s.min_distance_cm, 1)} cm`;
        summary.append(
          el('span', { class: `tag ${s.collisions ? 'error' : 'ok'}`,
            text: `${s.collisions || 0} kolizji` }),
          el('span', { class: `tag ${s.warnings ? 'warning' : 'ok'}`,
            text: `${s.warnings || 0} ostrzeżeń` }),
          el('span', { class: 'tag ok',
            text: `${s.gates_passed || 0}/${s.gates_total || 0} bramek` }),
          el('span', { class: 'hint', text: `min. odstęp: ${minText}` }),
        );
      }
    }
    const box = $('#obs-findings');
    if (!box) return;
    box.innerHTML = '';
    if (!store.findings.length) {
      box.append(el('div', { class: 'empty', text: report
        ? 'Brak kolizji i zbliżeń na tej trasie.'
        : 'Uruchom symulację z wybraną sceną.' }));
      return;
    }
    for (const finding of store.findings) {
      const label = finding.level === 'collision' ? 'Kolizja'
        : (finding.level === 'warning' ? 'Zbliżenie' : 'Bramka');
      box.append(el('div', {
        class: `issue obs-issue ${finding.level}`,
        title: 'Kliknij, aby przejść do chwili zdarzenia',
        onclick: () => ctx.seek?.(finding.t),
      }, [
        el('div', { class: 'head' }, [
          el('span', { text: label }),
          el('span', { text: `t=${fmt(finding.t, 2)} s · ${finding.obstacle_name}` }),
        ]),
        el('div', { class: 'msg', text: finding.message }),
      ]));
    }
  }

  // ------------------------------------------------------------ ustawienia
  function bindSettings() {
    const margin = $('#obs-margin');
    if (margin) {
      margin.value = String(settings.margin);
      margin.addEventListener('change', () => {
        settings.margin = Math.max(0, Math.min(200, Number(margin.value) || 0));
        margin.value = String(settings.margin);
        saveSettings(settings);
      });
    }
    const view = $('#obs-view');
    if (view) {
      view.value = settings.view;
      view.addEventListener('change', () => {
        settings.view = view.value;
        saveSettings(settings);
        const layer = getLayer(); if (layer) layer.setViewMode(settings.view);
      });
    }
    const labels = $('#obs-labels');
    if (labels) {
      labels.checked = settings.labels;
      labels.addEventListener('change', () => {
        settings.labels = labels.checked;
        saveSettings(settings);
        const layer = getLayer(); if (layer) layer.setLabels(settings.labels);
      });
    }
    const stop = $('#obs-stop-collision');
    if (stop) {
      stop.checked = settings.stopOnCollision;
      stop.addEventListener('change', () => {
        settings.stopOnCollision = stop.checked;
        saveSettings(settings);
        ctx.setStopOnCollision?.(stop.checked);
      });
    }
    const edit = $('#obs-edit');
    if (edit) {
      edit.addEventListener('change', () => {
        const layer = getLayer(); if (layer) layer.setEditMode(edit.checked, editCallbacks);
        setStatus(edit.checked ? 'Tryb edycji: przeciągaj przeszkody po podłożu.'
          : 'Tryb edycji wyłączony.', '');
      });
    }
    $('#obs-add-box')?.addEventListener('click', () => addObstacle('box'));
    $('#obs-add-cylinder')?.addEventListener('click', () => addObstacle('cylinder'));
    $('#obs-add-gate')?.addEventListener('click', () => addObstacle('gate'));
    $('#obs-add-plane')?.addEventListener('click', () => addObstacle('plane'));
    $('#obs-add-mission-pad')?.addEventListener('click', () => addObstacle('mission_pad'));
    $('#obs-new')?.addEventListener('click', newScene);
    $('#obs-save')?.addEventListener('click', () => saveScene());
    $('#obs-save-as')?.addEventListener('click', () => {
      const name = window.prompt('Nazwa nowej sceny (plik w scenes/user):',
        `${store.scene?.name || 'scena'}-kopia`);
      if (!name) return;
      store.scene.name = name;
      saveScene(name);
    });
    $('#obs-reload')?.addEventListener('click', refreshScenes);
  }

  const editCallbacks = {
    onSelect: (id) => selectObstacle(id),
    onDrag: (id, x, y) => {
      const obstacle = store.scene?.obstacles.find((o) => o.id === id);
      if (!obstacle) return;
      obstacle.position[0] = Math.round(x * 10) / 10;
      obstacle.position[1] = Math.round(y * 10) / 10;
      markDirty();
    },
    onDragEnd: () => {
      renderList();
      renderEditor();
      ctx.setActiveScene?.(store.scene);
    },
  };

  /** Wczytaj lot z historii: pokaż jego scenę i raport kolizji. */
  function onFlightLoaded(flight) {
    const scene = flight?.obstacles?.scene || flight?.scene || null;
    if (scene) {
      store.scene = scene;
      store.name = '';
      store.isUserScene = false;
      store.selectedId = null;
      notifySaved();
      applyToScene();
      renderFindings(flight.obstacles || null);
      setStatus('Scena wczytana z lotu.', '');
      return;
    }
    if (store.findings.length) renderFindings(null);
  }

  /** Bieżąca scena do zapisania razem z lotem (``options.obstacles``). */
  function getRunOptions() {
    if (!store.scene) return {};
    return { obstacles: { scene: store.scene, margin_cm: settings.margin } };
  }

  async function init() {
    bindSettings();
    await refreshScenes();
    // Pierwsze uruchomienie: pusta scena robocza (bez bramek ani przeszkód).
    // Dopiero gdy użytkownik wcześniej wybrał scenę - wracamy do niej.
    const remembered = loadScenePreference();
    const known = Boolean(remembered)
      && store.list.some((item) => item.name === remembered);
    if (known) await loadScene(remembered);
    else await newScene();
    if (getLayer()) {
      syncLayer();
      ctx.scene?.fitView?.();
    }
    ctx.setStopOnCollision?.(settings.stopOnCollision);
  }

  const panel = {
    init,
    onFlightLoaded,
    getRunOptions,
    setFindings: renderFindings,
    getFindings: () => store.findings,
    getScene: () => store.scene,
    get marginCm() { return settings.margin; },
    get stopOnCollision() { return settings.stopOnCollision; },
  };
  ctx.panels.register(panel);
  init();
}

