// Tryb wydajności: „Automatycznie” / „Pełna” / „Lekka”.
//
// Tryb lekki jest dla słabych komputerów (bez GPU, wolny CPU): mniej pracy na
// klatkę i renderowanie tylko wtedy, gdy coś się zmienia. Ustawienie jest
// zapamiętywane w localStorage (w try/catch - brak storage nie jest błędem),
// a parametr adresu `?lite=1` wymusza tryb lekki bez zapisu.
//
// Klucz ustawienia zawiera **edycję** wydania (`dronesim.perf:standard` albo
// `dronesim.perf:for_potatoes`): tryb lekki zapisany w wydaniu „for_potatoes”
// nie przechodzi do edycji standardowej (i odwrotnie).
//
// Automatycznie: po wczytaniu aplikacji mierzymy ~2 s klatek; jeśli wychodzi
// mniej niż 30 FPS, proponujemy tryb lekki (Tak / Nie / Nie pytaj więcej).

//: prefiks klucza; pełny klucz to ``<prefiks>:<edycja>``
const STORAGE_PREFIX = 'dronesim.perf';
//: przyrostek klucza „nie pytaj więcej o tryb lekki” (też z edycją)
const ASK_SUFFIX = '.ask';
//: poniżej tylu FPS proponujemy tryb lekki
export const SLOW_FPS = 30;
//: czas pomiaru w trybie automatycznym [ms]
const PROBE_MS = 2000;

//: edycja wydania ustawiana na starcie (``initPerf({ edition })``)
let editionKey = 'standard';

/** Klucz ustawienia trybu wydajności dla danej edycji. */
export function storageKey(edition = editionKey) {
  return `${STORAGE_PREFIX}:${edition}`;
}

/** Klucz „nie pytaj więcej” dla danej edycji. */
export function askKey(edition = editionKey) {
  return `${STORAGE_PREFIX}${ASK_SUFFIX}:${edition}`;
}

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

/** Wczytaj zapamiętane ustawienie i wymuszenie z adresu (bez mierzenia FPS).
 *
 * @param {object} [options]
 * @param {string} [options.edition] - edycja wydania (``standard`` /
 *   ``for_potatoes``); ustawienie jest pamiętane **osobno** dla każdej edycji
 */
export function initPerf(options = {}) {
  if (options.edition) editionKey = String(options.edition);
  const params = new URLSearchParams(window.location.search);
  const query = (params.get('lite') || '').toLowerCase();
  const stored = loadFromStorage(storageKey(), 'auto');
  mode = ['auto', 'full', 'lite'].includes(stored) ? stored : 'auto';
  if (query === '1' || query === 'true') {
    forced = true;
    mode = 'lite';
  }
  if (mode === 'lite') apply(true, { silent: true });
  else if (mode === 'full') apply(false, { silent: true });
  return { mode, forced, key: storageKey() };
}

/** Zapisz wybór użytkownika i zastosuj tryb.
 *
 * „Automatycznie” **nie włącza** trybu lekkiego samo - tylko proponuje go po
 * pomiarze FPS (pytanie Tak/Nie/Nie pytaj więcej). Dopóki użytkownik nie
 * odpowie „Tak”, scena rysuje w trybie pełnym.
 */
export function setMode(next, options = {}) {
  const value = ['auto', 'full', 'lite'].includes(next) ? next : 'auto';
  mode = value;
  forced = false;
  saveToStorage(storageKey(), value === 'auto' ? null : value);
  if (value === 'full') apply(false, options);
  else if (value === 'lite') apply(true, options);
  else apply(false, options);          // „auto” = pełny do decyzji użytkownika
}

/** Czy użytkownik wyłączył pytanie o tryb lekki? */
export function askingDisabled() {
  return loadFromStorage(askKey(), '0') === '1';
}

/** Zapamiętaj „nie pytaj więcej”. */
export function disableAsking() {
  saveToStorage(askKey(), '1');
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
 * Tryb automatyczny: zmierz FPS i **zaproponuj** tryb lekki (nic nie włączaj).
 *
 * Propozycja pojawia się tylko raz, gdy klatki są wolniejsze niż ``SLOW_FPS``
 * i użytkownik nie wybrał wcześniej „Nie pytaj więcej”. Tryb lekki włącza się
 * dopiero po kliknięciu „Tak” (``rememberAnswer(true)``); „Nie” i „Nie pytaj
 * więcej” zostawiają tryb pełny.
 *
 * @param {Function} propose funkcja pokazująca pytanie (Tak/Nie/Nie pytaj więcej)
 * @returns {Promise<{fps: number, lite: boolean, asked: boolean}>}
 */
export async function autoDetect(propose) {
  if (forced || mode !== 'auto') {
    return { fps: null, lite, asked: false };
  }
  const fps = await measureFps();
  const slow = fps < SLOW_FPS;
  if (!slow || askingDisabled()) {
    return { fps, lite, asked: false };     // nic nie proponujemy i nic nie zmieniamy
  }
  propose({ fps, enable: () => rememberAnswer(true), disable: () => rememberAnswer(false),
    neverAsk: () => rememberAnswer(false, true) });
  return { fps, lite, asked: true };
}
