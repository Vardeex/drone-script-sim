// Punkt rozszerzeń nr 4: rejestracja funkcji (wtyczek) w interfejsie.
//
// Rdzeń nie zna nazw funkcji. Pobiera listę z /api/features (te same manifesty
// co backend) i dla każdej funkcji:
//   1. doładowuje jej arkusze stylów (manifest.ui.styles),
//   2. importuje moduł panelu (manifest.ui.panel) -> rozszerza `panels`,
//   3. importuje warstwę sceny 3D (manifest.ui.scene_layer) -> `sceneLayers`.
// Funkcja wyłączona w config.json nie trafia na listę - jej pliki nie są
// serwowane i nic się nie doładowuje.

import * as panels from './panels.js';

//: baza serwowania plików funkcji (rdzeń montuje /static/features/<id>)
const FEATURE_BASE = '/static/features';

/** Warstwy sceny 3D zarejestrowane przez funkcje: [{ id, factory }] */
export const sceneLayers = [];

function loadStyles(files = []) {
  for (const href of files) {
    if (document.querySelector(`link[data-feature="${href}"]`)) continue;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = `/${href}`;
    link.dataset.feature = href;
    document.head.append(link);
  }
}

/** Ścieżka modułu funkcji: nazwa pliku z manifestu pod bazą funkcji. */
function moduleUrl(feature, path, version = '') {
  const suffix = version ? `?v=${version}` : '';
  return `${FEATURE_BASE}/${feature.id}/${path.split('/').pop()}${suffix}`;
}

/**
 * Wczytaj i zarejestruj wszystkie włączone funkcje.
 * @param {{scene: object, player: object, timeline: object}} context
 * @returns {Promise<Array<object>>} opis wczytanych funkcji
 */
export async function registerFeatures(context = {}) {
  let features = [];
  try {
    const response = await fetch('/api/features');
    features = response.ok ? await response.json() : [];
  } catch (err) {
    console.warn('Nie udało się pobrać listy funkcji:', err);
    return [];
  }
  const loaded = [];
  for (const feature of features) {
    const ui = feature.ui || {};
    const errors = [];
    loadStyles(ui.styles);
    if (ui.panel) {
      try {
        const module = await import(moduleUrl(feature, ui.panel, context.version));
        if (typeof module.registerPanel === 'function') {
          module.registerPanel({
            panels: { register: (api) => panels.registerFeaturePanel(feature.id, api) },
            feature,
            ...context,
          });
        }
        // przycisk zakładki pokazujemy dopiero, gdy panel istnieje
        const button = document.getElementById(ui.tab_button || `tab-btn-${feature.id}`);
        const content = document.getElementById(ui.tab || `tab-${feature.id}`);
      if (button) button.hidden = false;
      } catch (err) {
        errors.push(`panel: ${err && err.message}`);
        console.error(`Funkcja ${feature.id} - panel nie został wczytany:`, err);
      }
    }
    if (ui.scene_layer) {
      try {
        const module = await import(moduleUrl(feature, ui.scene_layer, context.version));
        if (typeof module.createLayer === 'function') {
          sceneLayers.push({ id: feature.id, factory: module.createLayer });
        }
      } catch (err) {
        errors.push(`warstwa 3D: ${err && err.message}`);
        console.error(`Funkcja ${feature.id} - warstwa sceny nie została wczytana:`, err);
      }
    }
    window.__featureErrors = { ...(window.__featureErrors || {}), [feature.id]: errors };
    if (!errors.length) loaded.push(feature);
  }
  return loaded;
}
/** Dodaj warstwy funkcji do sceny (wywoływane po jej utworzeniu). */
export function attachSceneLayers(scene, context = {}) {
  const statuses = [];
  for (const layer of sceneLayers) {
    try {
      const instance = layer.factory({ scene, ...context });
      if (instance) {
        scene.addOverlayLayer(instance);
        statuses.push({ id: layer.id, instance });
      }
    } catch (err) {
      console.error(`Warstwa sceny ${layer.id} nie została podłączona:`, err);
    }
  }
  return statuses;
}
