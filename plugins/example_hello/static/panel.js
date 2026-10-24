// Panel przykładowej wtyczki (punkt rozszerzeń ``ui.panel``).
//
// Rdzeń wywołuje `registerPanel({ panels, feature, ...context })` po
// wczytaniu tego pliku. `panels.register(api)` zgłasza panel pod id wtyczki:
//   * `mount(section)` - wypełnia treść zakładki (sekcja o id `ui.tab`),
//   * `getRunOptions()` - opcjonalne opcje uruchomienia (punkt ``run.options``),
//   * `onLoad(payload)` - opcjonalna reakcja na wczytany lot.
//
// Wtyczka nie zna nazw funkcji rdzenia - dostaje tylko to, co jest w `context`
// (scene, player, timeline) oraz własny `feature` (manifest).

const PANEL_HTML = `
  <div class="section">
    <h2>Przykładowa wtyczka</h2>
    <p class="hint">
      Ten panel pochodzi z <code>plugins/example_hello</code>. Pokazuje, jak
      wtyczka zewnętrzna dodaje zakładkę i korzysta z endpointu API.
    </p>
    <p class="hello-text" data-hello-text>Witaj! To statyczny tekst z wtyczki.</p>
    <div class="row">
      <button type="button" data-hello-ping>Zapytaj API wtyczki</button>
    </div>
    <div class="hint" data-hello-status>API jeszcze nie pytane.</div>
  </div>
`;

/** Zamontuj panel w sekcji zakładki. */
function mount(section) {
  if (!section) return;
  section.innerHTML = PANEL_HTML;
  const status = section.querySelector('[data-hello-status]');
  const button = section.querySelector('[data-hello-ping]');
  if (button && status) {
    button.addEventListener('click', async () => {
      status.textContent = 'Pytam /api/example_hello/hello …';
      try {
        const response = await fetch('/api/example_hello/hello?name=wtyczko');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        status.textContent = data.message;
      } catch (err) {
        status.textContent = `Błąd API wtyczki: ${err && err.message}`;
      }
    });
  }
}

/** Rejestracja panelu (wywoływana przez rdzeń). */
export function registerPanel({ panels, feature }) {
  panels.register({
    mount,
    // wtyczka nie potrzebuje opcji uruchomienia - zostawiamy pusty obiekt
    getRunOptions: () => ({}),
  });
  console.info(`Wtyczka ${feature.id} ${feature.version}: panel gotowy.`);
}
