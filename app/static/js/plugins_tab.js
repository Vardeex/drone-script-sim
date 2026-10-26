// Zakładka „Wtyczki”: lista wtyczek (wbudowane + zewnętrzne) ze stanem
// i przełącznikiem włącz/wyłącz. Stan zapisuje się w config.json serwera
// i obowiązuje po restarcie - UI wyraźnie to komunikuje.
import { $, el } from './util.js';
import { api } from './api.js';

const STATE_LABEL = {
  enabled: 'włączona',
  disabled: 'wyłączona',
  error: 'błąd',
};

const SOURCE_LABEL = {
  builtin: 'wbudowana',
  external: 'zewnętrzna',
};

/** Pojedyncza karta wtyczki. */
function pluginCard(plugin, onChange) {
  const state = plugin.state || 'disabled';
  const card = el('div', { class: `plugin-card state-${state}` });
  card.dataset.plugin = plugin.id;

  const head = el('div', { class: 'plugin-head' });
  head.append(el('span', { class: 'plugin-name', text: plugin.name || plugin.id }));
  head.append(el('span', { class: `tag plugin-state ${state}`, text: STATE_LABEL[state] || state }));
  head.append(el('span', { class: 'tag ghost', text: SOURCE_LABEL[plugin.source] || plugin.source }));
  card.append(head);

  const meta = el('div', { class: 'hint plugin-meta' });
  meta.append(el('span', { class: 'mono', text: `${plugin.id} ${plugin.version || ''}`.trim() }));
  if (plugin.author) meta.append(el('span', { text: ` · autor: ${plugin.author}` }));
  if (plugin.requires && plugin.requires.length) {
    meta.append(el('span', { text: ` · wymaga: ${plugin.requires.join(', ')}` }));
  }
  if (plugin.extension_points && plugin.extension_points.length) {
    meta.append(el('span', { class: 'plugin-points', text: ` · ${plugin.extension_points.join(', ')}` }));
  }
  card.append(meta);

  card.append(el('div', { class: 'plugin-desc', text: plugin.description || '—' }));

  if (state === 'error' && plugin.error) {
    card.append(el('div', { class: 'plugin-error', text: `Błąd: ${plugin.error}` }));
  }

  const row = el('div', { class: 'row plugin-actions' });
  const toggle = el('input', { type: 'checkbox' });
  toggle.checked = state === 'enabled';
  toggle.dataset.pluginToggle = plugin.id;
  // wtyczki z błędem nie da się „włączyć" bez poprawienia kodu - przełącznik
  // zostawiamy aktywny, bo użytkownik może chcieć ją wyłączyć na stałe.
  const label = el('label', { class: 'hint' }, [toggle, document.createTextNode(' włączona')]);
  toggle.addEventListener('change', async () => {
    toggle.disabled = true;
    try {
      await onChange(plugin.id, toggle.checked);
    } finally {
      toggle.disabled = false;
    }
  });
  row.append(label);
  card.append(row);
  return card;
}

/** Wczytaj i wyrenderuj zakładkę wtyczek. */
export async function renderPlugins() {
  const list = $('#plugins-list');
  const meta = $('#plugins-meta');
  const points = $('#plugins-points');
  if (!list) return;
  let data;
  try {
    data = await api.plugins();
  } catch (err) {
    list.innerHTML = '';
    list.append(el('div', { class: 'plugin-error', text: `Nie udało się pobrać wtyczek: ${err.message}` }));
    return;
  }
  const plugins = data.plugins || [];
  if (meta) {
    const enabled = plugins.filter((p) => p.state === 'enabled').length;
    const broken = plugins.filter((p) => p.state === 'error').length;
    meta.textContent = `Aplikacja ${data.display_name || data.app_version}`
      + ` · wtyczek: ${plugins.length}`
      + ` · włączonych: ${enabled}` + (broken ? ` · z błędem: ${broken}` : '');
  }
  if (points) {
    points.innerHTML = '';
    for (const point of data.extension_points || []) {
      points.append(el('div', { class: 'plugin-point' }, [
        el('code', { text: point.id }),
        document.createTextNode(` — ${point.description}`),
      ]));
    }
  }
  list.innerHTML = '';
  if (!plugins.length) {
    list.append(el('div', { class: 'empty', text: 'Brak wtyczek.' }));
    return;
  }
  const status = (text, kind = '') => {
    let line = $('#plugins-status');
    if (!line) {
      line = el('div', { class: 'hint', id: 'plugins-status' });
      list.after(line);
    }
    line.className = `hint ${kind}`;
    line.textContent = text;
  };
  const onChange = async (id, enabled) => {
    try {
      const answer = await api.setPluginEnabled(id, enabled);
      await renderPlugins();
      status(`Wtyczka „${id}”: ${enabled ? 'włączona' : 'wyłączona'}. `
        + `${answer.message}`, 'warn-text');
    } catch (err) {
      status(`Nie udało się zmienić stanu wtyczki „${id}”: ${err.message}`, 'warn-text');
    }
  };
  for (const plugin of plugins) list.append(pluginCard(plugin, onChange));
}
