// Funkcje pomocnicze: formatowanie liczb, kolory wysokości, DOM.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const fmt = (value, digits = 1) =>
  (value === null || value === undefined || Number.isNaN(Number(value)))
    ? '—' : Number(value).toFixed(digits);

export function fmtTime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Number(seconds));
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return m > 0 ? `${m}:${rest.toFixed(1).padStart(4, '0')}` : `${rest.toFixed(1)} s`;
}

// ------------------------------------------------------------------ kolory
// Paleta wysokości (niebieski -> zielony -> żółty -> czerwony).
const STOPS = [
  [0.0, [59, 130, 246]],   // #3b82f6 niebieski
  [0.35, [34, 197, 94]],   // #22c55e zielony
  [0.65, [234, 179, 8]],   // #eab308 żółty
  [1.0, [239, 68, 68]],    // #ef4444 czerwony
];

export function colorForHeight(z, maxZ) {
  const max = Math.max(maxZ, 1);
  const frac = Math.min(Math.max(z / max, 0), 1);
  for (let i = 1; i < STOPS.length; i += 1) {
    const [stop, color] = STOPS[i];
    const [prevStop, prevColor] = STOPS[i - 1];
    if (frac <= stop) {
      const t = (frac - prevStop) / (stop - prevStop || 1);
      return prevColor.map((c, k) => Math.round(c + (color[k] - c) * t));
    }
  }
  return STOPS[STOPS.length - 1][1];
}

export function cssColor(rgb, alpha = 1) {
  const [r, g, b] = rgb;
  return alpha >= 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
}

export function legendGradient() {
  const parts = STOPS.map(([stop, color]) => `${cssColor(color)} ${(stop * 100).toFixed(0)}%`);
  return `linear-gradient(90deg, ${parts.join(', ')})`;
}

export function debounce(fn, ms = 150) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function clamp(value, low, high) {
  return Math.min(Math.max(value, low), high);
}

export function formatArgs(command, args) {
  if (!args || !args.length) return '—';
  return args.map((a) => (typeof a === 'string' ? `"${a}"` : String(a))).join(', ');
}

//: "1 błąd" / "2 błędy" / "5 błędów" - polska odmiana liczebnika
export function plural(n, one, few, many) {
  const count = Math.abs(Number(n) || 0);
  if (count === 1) return one;
  const last = count % 10;
  const lastTwo = count % 100;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return few;
  return many;
}

export const STATUS_LABEL = {
  ok: 'OK', warning: 'ostrzeżenie', error: 'błąd',
  airborne: 'w locie', idle: 'na ziemi', landed: 'wylądował',
  emergency: 'awaryjne', running: 'uruchamianie', done: 'gotowe', timeout: 'timeout',
  stopped: 'przerwany', failed: 'błąd serwera',
};
