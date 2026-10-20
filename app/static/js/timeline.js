// Model czasu lotu: próbki telemetrii, komendy, segmenty, odtwarzanie.
//
// Układ w UI: three.js używa Y jako góry, więc poza modelem czasu
// zamieniamy osie: (x, y, z) drona -> (x, z, -y) w scenie.

import { clamp } from './util.js';

export function toScene(pos) {
  return { x: pos.x, y: pos.z, z: -pos.y };
}

export class FlightTimeline {
  constructor() {
    this.reset();
  }

  reset() {
    this.samples = [];
    this.events = [];
    this.segments = [];
    this.warnings = [];
    this.errors = [];
    this.stdout = [];
    this.stderr = [];
    this.stats = {};
    this.source = '';
    this.scriptName = 'skrypt.py';
    this.adapter = 'tello';
    this.flightId = null;
    this.duration = 0;
    this.status = 'ok';
    this.finalState = 'idle';
    this.listeners = new Set();
  }

  /**
   * Wczytaj lot. ``data`` to format zapisu (storage.flight_to_dict)
   * lub obiekt symulacji na żywo (samples/events/segments/stats).
   */
  load(data, meta = {}) {
    this.reset();
    if (!data) return;
    this.samples = (data.samples || []).slice().sort((a, b) => a.t - b.t);
    this.events = (data.events || []).slice();
    this.segments = data.segments || [];
    this.warnings = data.warnings || [];
    this.errors = data.errors || [];
    this.stdout = data.stdout || [];
    this.stderr = data.stderr || [];
    this.stats = data.stats || {};
    this.source = data.script_source || meta.source || '';
    this.scriptName = data.script_name || meta.scriptName || 'skrypt.py';
    this.adapter = data.adapter || meta.adapter || 'tello';
    this.status = data.status || meta.status || 'ok';
    this.finalState = data.final_state || data.finalState || 'idle';
    this.flightId = meta.flightId || data.id || null;
    const lastSample = this.samples.length ? this.samples[this.samples.length - 1].t : 0;
    const lastEvent = this.events.length
      ? (this.events[this.events.length - 1].t_end || this.events[this.events.length - 1].t) : 0;
    this.duration = Math.max(Number(data.duration) || 0, lastSample, lastEvent);
    this.scriptSpan = [this.startTime(), lastEvent];
    this.emit();
  }

  startTime() {
    return this.events.length ? this.events[0].t : 0;
  }

  // -------------------------------------------------------- pozycja w czasie
  sampleAt(t) {
    const s = this.samples;
    if (!s.length) return defaultSample(t);
    if (t <= s[0].t) return s[0];
    if (t >= s[s.length - 1].t) return s[s.length - 1];
    // wyszukiwanie binarne pary próbek
    let low = 0;
    let high = s.length - 1;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (s[mid].t <= t) low = mid; else high = mid;
    }
    const a = s[low];
    const b = s[high];
    const span = b.t - a.t;
    const frac = span > 0 ? (t - a.t) / span : 0;
    const lerp = (k) => a[k] + (b[k] - a[k]) * frac;
    const dyaw = ((b.yaw - a.yaw + 540) % 360) - 180; // najkrótsza droga
    return {
      t,
      x: lerp('x'), y: lerp('y'), z: lerp('z'),
      yaw: (a.yaw + dyaw * frac + 360) % 360,
      vx: lerp('vx'), vy: lerp('vy'), vz: lerp('vz'),
      battery: lerp('battery'),
      state: frac < 0.5 ? a.state : b.state,
    };
  }

  speedAt(t) {
    const sample = this.sampleAt(t);
    return Math.hypot(sample.vx, sample.vy, sample.vz);
  }

  // --------------------------------------------------- zdarzenia (komendy)
  /** Indeks ostatniej komendy, która rozpoczęła się do chwili t (-1 = brak). */
  eventIndexAt(t) {
    let index = -1;
    for (let i = 0; i < this.events.length; i += 1) {
      if (this.events[i].t <= t + 1e-9) index = i; else break;
    }
    return index;
  }

  /** Komenda, podczas której trwa chwila t (t między t a t_end). */
  activeEventAt(t) {
    const index = this.eventIndexAt(t);
    return index < 0 ? null : this.events[index];
  }

  nextEventTime(t) {
    for (const e of this.events) if (e.t > t + 1e-6) return e.t;
    return null;
  }

  prevEventTime(t) {
    let result = null;
    for (const e of this.events) {
      if (e.t < t - 0.15) result = e.t; else break;
    }
    return result;
  }

  // ------------------------------------------------------------ statystyki
  computedStats() {
    const stats = { ...this.stats };
    if (!stats.duration_s) stats.duration_s = this.duration;
    if (!stats.samples) stats.samples = this.samples.length;
    if (!stats.events) stats.events = this.events.length;
    if (stats.warnings === undefined) stats.warnings = this.warnings.length;
    if (stats.errors === undefined) stats.errors = this.errors.length;
    return stats;
  }

  maxHeight() {
    if (!this.samples.length) return 0;
    let max = 0;
    for (const s of this.samples) if (s.z > max) max = s.z;
    return max;
  }

  // --------------------------------------------------------------- sygnały
  onChange(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit() {
    for (const fn of this.listeners) fn(this);
  }
}

function defaultSample(t) {
  return { t, x: 0, y: 0, z: 0, yaw: 0, vx: 0, vy: 0, vz: 0, battery: 100, state: 'idle' };
}

export class Player {
  constructor(timeline, onFrame) {
    this.timeline = timeline;
    this.onFrame = onFrame;
    this.t = 0;
    this.speed = 1;
    this.playing = false;
    this._last = 0;
    this._raf = null;
  }

  setTime(t, silent = false) {
    this.t = clamp(t, 0, Math.max(this.timeline.duration, 0));
    if (!silent) this.onFrame(this.t);
  }

  seek(t) {
    this.setTime(t);
  }

  play() {
    if (this.playing || this.timeline.duration <= 0) return;
    if (this.t >= this.timeline.duration - 1e-6) this.t = 0;
    this.playing = true;
    this._last = performance.now();
    this._tick();
  }

  pause() {
    this.playing = false;
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  toggle() {
    if (this.playing) this.pause(); else this.play();
  }

  _tick = () => {
    if (!this.playing) return;
    const now = performance.now();
    const dt = (now - this._last) / 1000;
    this._last = now;
    this.t += dt * this.speed;
    if (this.t >= this.timeline.duration) {
      this.t = this.timeline.duration;
      this.onFrame(this.t);
      this.playing = false;
      return;
    }
    this.onFrame(this.t);
    this._raf = requestAnimationFrame(this._tick);
  };
}
