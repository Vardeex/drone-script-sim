// Edytor skryptów: CodeMirror 6 z lokalnego bundla (bez CDN).
//
// Dlaczego osobny moduł: rdzeń (app.js, panels.js) nie może wiedzieć, jaki
// edytor jest w środku. Tutaj jest cała integracja:
//
// * montuje CodeMirror nad ``<textarea id="editor-area">``, a textarea zostaje
//   **ukrytym źródłem prawdy** - dzięki temu cały dotychczasowy kod
//   (``$('#editor-area').value``, testy, formularz uruchomienia) działa bez zmian,
// * po każdej zmianie w edytorze aktualizuje textarea i wysyła zdarzenie
//   ``input`` (tak jakby użytkownik pisał w textarea),
// * po zmianie (z opóźnieniem) woła ``POST /api/check`` i pokazuje ostrzeżenia
//   pod edytorem + podkreśla linie,
// * udostępnia ``setPlaybackLine`` - podświetlenie aktualnie wykonywanej linii
//   podczas odtwarzania (wołane z ``panels.highlightCodeLine``).

import { createEditor } from '/static/vendor/codemirror/codemirror.bundle.js';
import { $ } from './util.js';

//: opóźnienie analizy po ostatniej zmianie [ms] - nie katujemy serwera każdą literą
const CHECK_DELAY_MS = 400;

let editor = null;
let timer = null;
let problems = [];

function renderProblems() {
  const box = $('#script-problems');
  if (!box) return;
  if (!problems.length) {
    box.hidden = true;
    box.textContent = '';
    window.__scriptProblems = [];
    return;
  }
  box.hidden = false;
  box.textContent = '';
  for (const problem of problems) {
    const row = document.createElement('div');
    row.className = `problem problem-${problem.level}`;
    row.textContent = (problem.level === 'error' ? '⛔' : '⚠')
      + ` linia ${problem.line ?? '?'}: ${problem.message}`;
    box.append(row);
  }
  // diagnostyka i testy przeglądarkowe
  window.__scriptProblems = problems.slice();
}

async function check(source) {
  try {
    const response = await fetch('/api/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    });
    if (!response.ok) return;
    const data = await response.json();
    problems = data.problems || [];
    renderProblems();
    editor?.markWarningLines(problems.map((item) => item.line).filter(Boolean));
  } catch (_) {
    /* brak serwera analizy nie może blokować edytora */
  }
}

function scheduleCheck(source) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => check(source), CHECK_DELAY_MS);
}

async function loadCompletions() {
  try {
    const response = await fetch('/api/completions');
    if (!response.ok) return;
    editor?.setCompletions(await response.json());
  } catch (_) {
    /* podpowiedzi są opcjonalne */
  }
}

/** Zamontuj edytor (wywoływane raz, po wczytaniu DOM). */
export function mountEditor() {
  const area = $('#editor-area');
  if (!area || editor) return editor;
  const host = document.createElement('div');
  host.id = 'editor-host';
  host.className = 'editor-host';
  area.parentNode.insertBefore(host, area);
  area.classList.add('editor-source-hidden');

  editor = createEditor({
    parent: host,
    doc: area.value,
    onChange(value) {
      area.value = value;
      area.dispatchEvent(new Event('input', { bubbles: true }));
      scheduleCheck(value);
    },
  });
  window.__editor = {
    getValue: () => editor.getValue(),
    setValue: setEditorValue,
    markWarningLines: (lines) => editor.markWarningLines(lines),
    setPlaybackLine: (line) => editor.setPlaybackLine(line),
    focus: () => editor.focus(),
  };
  loadCompletions();
  check(area.value);
  return editor;
}

/** Ustaw treść skryptu **i** w edytorze, i w ukrytej textarea. */
export function setEditorValue(text) {
  const area = $('#editor-area');
  if (area && area.value !== text) {
    area.value = text;
    area.dispatchEvent(new Event('input', { bubbles: true }));
  }
  editor?.setValue(text || '');
  scheduleCheck(text || '');
}

/** Bieżąca treść skryptu (jak ``$('#editor-area').value``). */
export function getEditorValue() {
  const area = $('#editor-area');
  return area ? area.value : '';
}

/** Wymuś natychmiastową analizę (używane przed uruchomieniem skryptu). */
export function recheck() {
  check(getEditorValue());
}
