// Tryb wydajności: „Automatycznie” / „Pełna” / „Lekka”.
//
// Tryb lekki jest dla słabych komputerów (bez GPU, wolny CPU): mniej pracy na
// klatkę i renderowanie tylko wtedy, gdy coś się zmienia. Ustawienie jest
// zapamiętywane w localStorage (w try/catch - brak storage nie jest błędem),
// a parametr adresu `?lite=1` wymusza tryb lekki bez zapisu.
//
// Automatycznie: po wczytaniu aplikacji mierzymy ~2 s klatek; jeśli wychodzi
// mniej niż 30 FPS, proponujemy tryb lekki (Tak / Nie / Nie pytaj więcej).

const STORAGE_KEY = 'dronesim.perf';
//: klucz „nie pytaj więcej o tryb lekki”
const ASK_KEY = 'dronesim.perf.ask';
//: poniżej tylu FPS proponujemy tryb lekki
export const SLOW_FPS = 30;
//: czas pomiaru w trybie automatycznym [ms]
const PROBE_MS = 2000;

const listeners = new Set();
let mode = 'auto';          // ustawienie użytkownika: auto | full | lite
let lite = false;           // faktyczny stan (wynik „auto” albo wymuszenie)
let forced = false;         // ?lite=1 - nie zapisujemy, nie pytamy
let applyHooks = [];        // funkcje wołane po zmianie stanu

/** Czy działa tryb lekki? */
export function isLite() {
  return lite;
}

/** Ustawienie użytkownika: ``auto`` / ``full`` / ``lite``. */
export function getMode() {
  return mode;
}

/** Czy tryb jest wymuszony parametrem adresu (``?lite=1``)? */
export function isForced() {
  return forced;
}

/** Rejestruj funkcję wołaną po każdej zmianie trybu (zwraca „odpinacz”). */
export function onPerfChange(callback) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function loadFromStorage(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

function saveToStorage(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (_) { /* prywatny tryb przeglądarki */ }
}

/** Wczytaj zapamiętane ustawienie i wymuszenie z adresu (bez mierzenia FPS). */
export function initPerf() {
  const params = new URLSearchParams(window.location.search);
  const query = (params.get('lite') || '').toLowerCase();
  const stored = loadFromStorage(STORAGE_KEY, 'auto');
  mode = ['auto', 'full', 'lite'].includes(stored) ? stored : 'auto';
  if (query === '1' || query === 'true') {
    forced = true;
    mode = 'lite';
  }
  if (mode === 'lite') apply(true, { silent: true });
  else if (mode === 'full') apply(false, { silent: true });
  return { mode, forced };
}

/** Zapisz wybór użytkownika i zastosuj tryb (``auto`` = decyzja przy starcie). */
export function setMode(next, options = {}) {
  const value = ['auto', 'full', 'lite'].includes(next) ? next : 'auto';
  mode = value;
  forced = false;
  saveToStorage(STORAGE_KEY, value === 'auto' ? null : value);
  if (value === 'full') apply(false, options);
  else if (value === 'lite') apply(true, options);
  else apply(autoDecision(), options);
}

/** Czy użytkownik wyłączył pytanie o tryb lekki? */
export function askingDisabled() {
  return loadFromStorage(ASK_KEY, '0') === '1';
}

/** Zapamiętaj „nie pytaj więcej”. */
export function disableAsking() {
  saveToStorage(ASK_KEY, '1');
}

/** Zapamiętaj decyzję z propozycji trybu lekkiego (Tak/Nie + opcjonalnie „nie pytaj”). */
export function rememberAnswer(enable, neverAsk = false) {
  apply(enable, { reason: 'answer' });
  if (neverAsk) disableAsking();
  if (enable) {
    mode = 'lite';
    saveToStorage(STORAGE_KEY, 'lite');
  }
}

let autoAnswer = null;

function autoDecision() {
  return autoAnswer === null ? false : autoAnswer;
}

function apply(value, options = {}) {
  const changed = lite !== value;
  lite = Boolean(value);
  for (const hook of applyHooks) {
    try {
      hook(lite);
    } catch (err) {
      console.error('perf: błąd przełączania trybu', err);
    }
  }
  if (!options.silent || changed) {
    for (const callback of listeners) {
      try {
        callback({ lite, mode, forced });
      } catch (err) {
        console.error('perf: błąd słuchacza', err);
      }
    }
  }
}

/** Dodatkowy „hook” przykładany do zmiany trybu (np. scena 3D). */
export function addApplyHook(hook) {
  applyHooks.push(hook);
  hook(lite);
}

/** Zmierz FPS przez ~2 s (rAF) i zwróć średnią. */
export function measureFps(durationMs = PROBE_MS) {
  return new Promise((resolve) => {
    const started = performance.now();
    let frames = 0;
    let first = 0;
    function tick(ts) {
      if (!first) first = ts;
      frames += 1;
      const elapsed = performance.now() - started;
      if (elapsed >= durationMs) {
        const span = ts - first;
        resolve(span > 0 ? ((frames - 1) * 1000) / span : 0);
        return;
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });
}

/**
 * Edycja aplikacji z serwera (``/api/edition``).
 *
 * Wydanie „for_potatoes” to ten sam kod w innym opakowaniu: plik
 * ``edition.json`` w katalogu programu mówi, że mamy tę edycję. Bez pliku
 * (albo gdy serwer nie odpowie w ``timeoutMs``) zwracamy edycję standardową,
 * więc zachowanie aplikacji z gita i wszystkich dotychczasowych testów się nie
 * zmienia.
 *
 * @param {number} timeoutMs limit czasu (ms) - nie blokujemy startu aplikacji
 */
export async function fetchEdition(timeoutMs = 1200) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch('/api/edition', { signal: controller.signal });
    if (!response.ok) return { edition: 'standard', version: null };
    const data = await response.json();
    return {
      edition: data.edition || 'standard',
      version: data.app_version || data.version || null,
      display_name: data.display_name || null,
      lite_default: Boolean(data.lite_default),
      features: data.features || {},
    };
  } catch (_) {
    return { edition: 'standard', version: null, lite_default: false, features: {} };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Tryb automatyczny: zmierz FPS i ewentualnie zaproponuj tryb lekki.
 *
 * @param {Function} propose funkcja pokazująca pytanie (Tak/Nie/Nie pytaj więcej)
 * @returns {Promise<{fps: number, lite: boolean, asked: boolean}>}
 */
export async function autoDetect(propose) {
  if (forced || mode !== 'auto') {
    return { fps: null, lite, asked: false };
  }
  const fps = await measureFps();
  autoAnswer = fps < SLOW_FPS;
  if (autoAnswer && !askingDisabled()) {
    propose({ fps, enable: () => rememberAnswer(true), disable: () => rememberAnswer(false),
      neverAsk: () => rememberAnswer(false, true) });
    return { fps, lite, asked: true };
  }
  if (autoAnswer) apply(true, { reason: 'auto' });
  return { fps, lite, asked: false };
}
