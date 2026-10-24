// Komunikacja z serwerem (FastAPI) - cienka warstwa nad fetch.

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = typeof body.detail === 'string'
        ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* odpowiedź bez JSON */ }
    throw new Error(detail);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response.text();
}

export const api = {
  adapters: () => request('/api/adapters'),
  plugins: () => request('/api/plugins'),
  setPluginEnabled: (id, enabled) => request(`/api/plugins/${encodeURIComponent(id)}/enabled`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  }),
  examples: () => request('/api/examples'),
  example: (name) => request(`/api/examples/${encodeURIComponent(name)}`),
  run: (payload) => request('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  live: (id) => request(`/api/run/live/${encodeURIComponent(id)}`),
  flights: (limit = 20) => request(`/api/flights?limit=${limit}`),
  flight: (id) => request(`/api/flights/${encodeURIComponent(id)}`),
  deleteFlight: (id) => request(`/api/flights/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  stopRun: (id) => request(`/api/run/stop/${encodeURIComponent(id)}`, { method: 'POST' }),
  importFlight: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/api/flights/import', { method: 'POST', body: form });
  },
};

export async function waitForRun(id, onUpdate, { interval = 250, maxMs = 180000 } = {}) {
  const deadline = Date.now() + maxMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await api.live(id);
    if (last.status !== 'running') return last;
    onUpdate?.(last);
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error('Przekroczono czas oczekiwania na zakończenie symulacji.');
}
