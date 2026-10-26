// Panele boczne: tabela komend, podgląd skryptu, konsola, problemy, statystyki.
import { $, el, fmt, fmtTime, formatArgs, STATUS_LABEL } from './util.js';
import { isLite } from './perf.js';

/**
 * Panele dostarczone przez funkcje (wtyczki): id -> API panelu.
 * Punkt rozszerzeń nr 4 - rdzeń czyta stąd wyłącznie przez `featurePanels[id]`.
 */
export const featurePanels = {};

/** Zarejestruj panel funkcji (wywołuje `boot.js` po wczytaniu modułu). */
export function registerFeaturePanel(id, api) {
  featurePanels[id] = api;
}

/**
 * Wiersze tabeli komend. Komendy RC wykonane w środku manewru (biblioteka
 * dronemoves) są zwijane w JEDEN wiersz: od ``start: X`` do ``end: X``.
 */
export function buildCommandRows(timeline) {
  const rows = [];
  let group = null;
  for (const event of timeline.events) {
    if (event.command === 'annotate') {
      const text = String((event.args || [])[0] || '');
      const isEnd = text.startsWith('end:');
      if (!isEnd && !group) {
        group = {
          kind: 'maneuver',
          label: text.replace(/^start:\s*/, ''),
          t: event.t,
          tEnd: event.t,
          count: 0,
          status: 'ok',
          x: event.x, y: event.y, z: event.z, yaw: event.yaw, battery: event.battery,
        };
        continue;
      }
      if (isEnd && group) {
        group.tEnd = event.t_end ?? event.t;
        rows.push(group);
        group = null;
        continue;
      }
    }
    if (group) {
      group.count += 1;
      group.tEnd = event.t_end ?? event.t;
      if (event.status === 'error') group.status = 'error';
      else if (event.status === 'warning' && group.status === 'ok') group.status = 'warning';
      continue;
    }
    rows.push({ kind: 'event', event, t: event.t, tEnd: event.t_end ?? event.t, count: 1 });
  }
  if (group) rows.push(group);
  return rows;
}

/** Indeks wiersza tabeli dla chwili ``t`` (z uwzględnieniem grup manewrów). */
export function commandRowIndexAt(timeline, t) {
  if (!timeline._commandRows) timeline._commandRows = buildCommandRows(timeline);
  const rows = timeline._commandRows;
  let index = -1;
  for (let i = 0; i < rows.length; i += 1) {
    if (rows[i].t <= t + 1e-9) index = i; else break;
  }
  return index;
}

//: powyżej tylu wierszy tryb lekki rysuje tylko okno tabeli (wirtualne przewijanie)
const VIRTUAL_THRESHOLD = 400;
const VIRTUAL_WINDOW = 240;
//: aktualnie narysowane okno wierszy tabeli komend
let rowWindow = { start: 0, count: 0 };
//: dane ostatniego renderowania (potrzebne, by przesunąć okno)
let lastRender = null;
let activeRowIndex = -1;

/** Okno wierszy tabeli komend (tryb lekki: ogranicz liczbę elementów DOM). */
function commandWindow(total) {
  if (!isLite() || total <= VIRTUAL_THRESHOLD) return { start: 0, count: total };
  const center = activeRowIndex >= 0 ? activeRowIndex : 0;
  const start = Math.max(0, Math.min(center - Math.floor(VIRTUAL_WINDOW / 2),
    total - VIRTUAL_WINDOW));
  return { start, count: VIRTUAL_WINDOW };
}

export function renderCommands(timeline, onSeek) {
  const tbody = $('#commands-table tbody');
  const empty = $('#commands-empty');
  tbody.innerHTML = '';
  const events = timeline.events;
  const rows = buildCommandRows(timeline);
  timeline._commandRows = rows;
  empty.hidden = rows.length > 0;
  // Tryb lekki + bardzo długi lot: rysujemy okno wierszy wokół aktywnego
  // miejsca (wirtualne przewijanie), żeby nie tworzyć tysięcy elementów DOM.
  const window = commandWindow(rows.length);
  const visible = window.count ? rows.slice(window.start, window.start + window.count) : rows;
  rowWindow = window;
  lastRender = { timeline, onSeek, rows };
  activeRowIndex = -1;
  const fragment = document.createDocumentFragment();
  visible.forEach((row, localIndex) => {
    const index = window.start + localIndex;
    if (row.kind === 'maneuver') {
      const duration = Math.max(row.tEnd - row.t, 0);
      const tr = el('tr', { class: `clickable maneuver status-${row.status}` });
      tr.dataset.t = String(row.t);
      tr.dataset.index = `m${index}`;
      tr.append(
        el('td', { class: 'mono', text: '◆' }),
        el('td', { class: 'mono', text: `${row.t.toFixed(2)}s` }),
        el('td', { class: 'mono', text: row.label }),
        el('td', { class: 'mono hint', text: `${row.count} komend RC · ${duration.toFixed(1)} s` }),
        el('td', { class: 'num', text: fmt(row.x, 0) }),
        el('td', { class: 'num', text: fmt(row.y, 0) }),
        el('td', { class: 'num', text: fmt(row.z, 0) }),
        el('td', { class: 'num', text: fmt(row.yaw, 0) }),
        el('td', { class: 'num', text: fmt(row.battery, 1) }),
        el('td', {}, [el('span', { class: `tag ${row.status}`, text: 'manewr' })]),
      );
      tr.title = `Manewr dronemoves: ${row.label} (${row.count} komend RC, ${duration.toFixed(2)} s)`;
      tr.addEventListener('click', () => onSeek(row.t));
      fragment.append(tr);
      return;
    }
    const event = row.event;
    const tr = el('tr', { class: `clickable status-${event.status}` });
    tr.dataset.t = String(event.t);
    tr.dataset.index = String(event.index);
    tr.append(
      el('td', { class: 'mono', text: String(event.index) }),
      el('td', { class: 'mono', text: `${event.t.toFixed(2)}s` }),
      el('td', { class: 'mono', text: event.command }),
      el('td', { class: 'mono hint', text: formatArgs(event.command, event.args) }),
      el('td', { class: 'num', text: fmt(event.x, 0) }),
      el('td', { class: 'num', text: fmt(event.y, 0) }),
      el('td', { class: 'num', text: fmt(event.z, 0) }),
      el('td', { class: 'num', text: fmt(event.yaw, 0) }),
      el('td', { class: 'num', text: fmt(event.battery, 1) }),
      el('td', {}, [el('span', {
        class: `tag ${event.status}`, text: STATUS_LABEL[event.status] || event.status,
      })]),
    );
    if (event.warning || event.message) tr.title = event.warning || event.message;
    tr.addEventListener('click', () => onSeek(event.t));
    fragment.append(tr);
  });
  tbody.append(fragment);
  const badge = document.querySelector('#badge-cmds');
  if (badge) {
    badge.textContent = String(events.length);
    badge.hidden = events.length === 0;
    badge.className = 'count';
  }
}

export function highlightCommandRow(index) {
  // tryb lekki z wirtualnym przewijaniem: przesuń okno, gdy aktywny wiersz
  // wyjechał poza nie (inaczej podświetlenie nie miałoby czego pokazać)
  const windowed = rowWindow.count > 0 && lastRender
    && rowWindow.count < lastRender.rows.length;
  if (windowed && (index < rowWindow.start
      || index >= rowWindow.start + rowWindow.count)) {
    activeRowIndex = index;
    renderCommands(lastRender.timeline, lastRender.onSeek);
  }
  const rows = $('#commands-table tbody').children;
  const local = index - rowWindow.start;
  for (let i = 0; i < rows.length; i += 1) {
    rows[i].classList.toggle('active', i === local);
  }
  activeRowIndex = index;
  if (local >= 0 && rows[local]) {
    const row = rows[local];
    const container = $('#tab-commands');
    if (!container.hidden) {
      const top = row.offsetTop - container.clientHeight / 2;
      container.scrollTo({ top, behavior: 'smooth' });
    }
  }
}

export function renderCodeView(source, errorLines = []) {
  const view = $('#code-view');
  view.innerHTML = '';
  const lines = (source || '').split('\n');
  const fragment = document.createDocumentFragment();
  lines.forEach((line, i) => {
    const n = i + 1;
    const row = el('div', {
      class: `code-line${errorLines.includes(n) ? ' errorline' : ''}`,
      'data-line': String(n),
    });
    row.append(el('span', { class: 'ln', text: String(n) }),
      el('span', { class: 'src', text: line || ' ' }));
    fragment.append(row);
  });
  view.append(fragment);
}

export function highlightCodeLine(line) {
  const view = $('#code-view');
  const current = view.querySelector('.code-line.current');
  if (current) current.classList.remove('current');
  // podświetlenie tej samej linii w edytorze (CodeMirror 6, patrz js/editor.js)
  window.__editor?.setPlaybackLine?.(line || null);
  if (!line) {
    $('#current-line-label').textContent = '';
    return;
  }
  const row = view.querySelector(`.code-line[data-line="${line}"]`);
  if (!row) return;
  row.classList.add('current');
  $('#current-line-label').textContent = `linia ${line}`;
  const top = row.offsetTop - view.clientHeight / 2 + row.offsetHeight / 2;
  view.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' });
}

export function renderConsole(timeline, live = false) {
  const box = $('#console');
  box.innerHTML = '';
  const add = (text, cls) => box.append(el('div', { class: cls, text }));
  if (live) add('— symulacja trwa —', 'meta');
  if (!timeline.stdout.length && !timeline.stderr.length) {
    add('(brak wyjścia skryptu)', 'meta');
  }
  for (const row of timeline.stdout) add(row.text, 'out');
  for (const row of timeline.stderr) add(row.text, 'err');
  box.scrollTop = box.scrollHeight;
}

function issueCard(issue, kind, onJump) {
  const card = el('div', { class: `issue ${kind}` });
  card.append(el('div', { class: 'head' }, [
    el('span', { text: kind === 'error' ? (issue.type || 'błąd') : 'ostrzeżenie' }),
    el('span', {
      text: [
        issue.file ? issue.file : null,
        issue.line ? `linia ${issue.line}` : null,
        issue.t !== undefined && issue.t !== null ? `t=${Number(issue.t).toFixed(2)}s` : null,
      ].filter(Boolean).join(' · ') || '—',
    }),
  ]));
  card.append(el('div', { class: 'msg', text: issue.message }));
  if (issue.traceback) {
    const details = el('details');
    details.append(el('summary', { class: 'hint', text: 'traceback' }),
      el('pre', { text: issue.traceback }));
    card.append(details);
  }
  if (issue.line && onJump) card.addEventListener('click', () => onJump(issue.line));
  return card;
}

export function renderIssues(timeline, onJumpLine) {
  const errorsBox = $('#errors-list');
  const warningsBox = $('#warnings-list');
  errorsBox.innerHTML = '';
  warningsBox.innerHTML = '';
  if (!timeline.errors.length) errorsBox.append(el('div', { class: 'empty', text: 'Brak błędów.' }));
  if (!timeline.warnings.length) {
    warningsBox.append(el('div', { class: 'empty', text: 'Brak ostrzeżeń.' }));
  }
  for (const issue of timeline.errors) errorsBox.append(issueCard(issue, 'error', onJumpLine));
  for (const issue of timeline.warnings) warningsBox.append(issueCard(issue, 'warning', onJumpLine));

  const badge = document.querySelector('#badge-issues');
  const total = timeline.errors.length + timeline.warnings.length;
  if (badge) {
    badge.textContent = String(total);
    badge.hidden = total === 0;
    badge.className = `count${timeline.errors.length ? '' : ' warn'}`;
  }

  // numerowana linia błędu w podglądzie kodu
  const errorLines = timeline.errors.filter((e) => e.line).map((e) => e.line);
  return errorLines;
}

export function renderStats(timeline) {
  const stats = timeline.computedStats();
  const grid = $('#stats-grid');
  grid.innerHTML = '';
  const entries = [
    ['Czas lotu', fmtTime(stats.duration_s), ''],
    ['Czas w powietrzu', fmtTime(stats.flight_time_s), ''],
    ['Dystans', stats.distance_cm !== undefined ? `${fmt(stats.distance_cm / 100, 1)} m` : '—', ''],
    ['Maks. wysokość', stats.max_height_cm !== undefined ? `${fmt(stats.max_height_cm / 100, 2)} m` : '—', ''],
    ['Zużycie baterii', stats.battery_used_pct !== undefined ? `${fmt(stats.battery_used_pct, 1)}%` : '—', ''],
    ['Pozycja końcowa', Array.isArray(stats.final_position_cm)
      ? stats.final_position_cm.map((v) => fmt(v, 0)).join(' / ') : '—', 'cm'],
    ['Yaw końcowy', stats.final_yaw_deg !== undefined ? `${fmt(stats.final_yaw_deg, 0)}°` : '—', ''],
    ['Komendy', String(stats.events ?? timeline.events.length), ''],
    ['Próbki telemetrii', String(stats.samples ?? timeline.samples.length), ''],
  ];
  for (const [label, value, unit] of entries) {
    grid.append(el('div', { class: 'stat' }, [
      el('div', { class: 'label', text: label }),
      el('div', { class: 'value', text: value }),
    ]));
  }
  const meta = $('#flight-meta');
  meta.textContent = `Skrypt: ${timeline.scriptName} · dron: ${timeline.adapter} · `
    + `stan: ${STATUS_LABEL[timeline.finalState] || timeline.finalState} · `
    + `status: ${STATUS_LABEL[timeline.status] || timeline.status}`
    + (timeline.flightId ? ` · id: ${timeline.flightId}` : '');
}
