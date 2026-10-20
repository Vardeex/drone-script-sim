// Dymek informacyjny dla znaczników komend na scenie 3D.
import { $, fmt, formatArgs } from './util.js';

const box = () => $('#tooltip');

function fill(event) {
  const tip = box();
  tip.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'cmd';
  title.textContent = `#${event.index}  ${event.command}(${formatArgs(event.command, event.args)})`;
  tip.append(title);

  const table = document.createElement('table');
  const rows = [
    ['Czas', `${event.t.toFixed(2)} s${event.t_end > event.t ? ` → ${event.t_end.toFixed(2)} s` : ''}`],
    ['Pozycja X / Y / Z', `${fmt(event.x, 0)} / ${fmt(event.y, 0)} / ${fmt(event.z, 0)} cm`],
    ['Wysokość', `${fmt(event.z / 100, 2)} m`],
    ['Yaw', `${fmt(event.yaw, 0)}°`],
    ['Bateria', `${fmt(event.battery, 1)}%`],
    ['Linia skryptu', event.line ? String(event.line) : '—'],
    ['Status', event.status],
  ];
  if (event.warning) rows.push(['Ostrzeżenie', event.warning]);
  if (event.message) rows.push(['Komunikat', event.message]);
  for (const [key, value] of rows) {
    const tr = document.createElement('tr');
    const td1 = document.createElement('td');
    td1.textContent = key;
    const td2 = document.createElement('td');
    td2.textContent = value;
    tr.append(td1, td2);
    table.append(tr);
  }
  tip.append(table);
}

export function showTooltip(event, x, y, viewport) {
  if (!event) {
    hideTooltip();
    return;
  }
  fill(event);
  const tip = box();
  tip.style.display = 'block';
  const rect = viewport.getBoundingClientRect();
  const width = tip.offsetWidth;
  const height = tip.offsetHeight;
  let left = x - rect.left + 14;
  let top = y - rect.top + 14;
  if (left + width > rect.width - 8) left = x - rect.left - width - 14;
  if (top + height > rect.height - 8) top = y - rect.top - height - 14;
  tip.style.left = `${Math.max(4, left)}px`;
  tip.style.top = `${Math.max(4, top)}px`;
}

export function hideTooltip() {
  box().style.display = 'none';
}
