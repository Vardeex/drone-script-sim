// Test modelu drona: obrys 98 × 92,5 × 41 mm (tolerancja ±2 mm), brak kolizji śmigieł.
//
// Liczy obrys z parametrów app/static/js/drone_model.js (TELLO_GEOMETRY_MM) tak,
// jak robi to model: najdalszy punkt śmigła/osłony w osi X i Z, góra osłony w Y.
// Uruchomienie: node tests/drone_model_bbox.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'app', 'static', 'js', 'drone_model.js'), 'utf8');

/** Wyciągnij liczby z bloku ``export const NAME = {...};`` (jedna lub wiele linii). */
function numbers(name) {
  const block = source.match(new RegExp(`export const ${name} = \\{([^}]*)\\}`));
  if (!block) throw new Error(`Brak ${name} w drone_model.js`);
  const out = {};
  for (const m of block[1].matchAll(/([A-Za-z]+):\s*([\d.]+)/g)) out[m[1]] = Number(m[2]);
  return out;
}

const geom = numbers('TELLO_GEOMETRY_MM');
const outline = numbers('TELLO_OUTLINE_MM');

// szerokość łopaty z createTello: BoxGeometry(..., ..., mm(5.2))
const BLADE_WIDTH_MM = 5.2;
const propHalf = geom.propDiameter / 2;
const guardHalf = propHalf + geom.guardExtra + geom.guardThickness / 2;

const measured = {
  length: 2 * Math.max(geom.motorX + propHalf, geom.motorX + guardHalf),
  width: 2 * Math.max(geom.motorZ + guardHalf, geom.motorZ + BLADE_WIDTH_MM / 2),
  height: geom.guardY + geom.guardThickness / 2,
};

const tolerance = 2.0; // mm
let failed = 0;
const check = (ok, text) => {
  if (!ok) failed += 1;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${text}`);
};

console.log(`model: ${measured.length.toFixed(1)} x ${measured.width.toFixed(1)} x ${measured.height.toFixed(1)} mm`);
for (const [name, key, target] of [
  ['dlugosc', 'length', outline.length],
  ['szerokosc', 'width', outline.width],
  ['wysokosc', 'height', outline.height],
]) {
  const diff = Math.abs(measured[key] - target);
  check(diff <= tolerance,
    `${name}: ${measured[key].toFixed(2)} mm (cel ${target} mm, odchylka ${diff.toFixed(2)} mm)`);
}

// śmigła sąsiednie nie mogą się przecinać (odległość osi > średnica śmigła)
const gapX = 2 * geom.motorX - geom.propDiameter;
const gapZ = 2 * geom.motorZ - geom.propDiameter;
check(gapX > 0 && gapZ > 0,
  `smigla nie koliduja (przerwa ${gapX.toFixed(1)} mm w X, ${gapZ.toFixed(1)} mm w Z)`);

// dno drona na podłożu: model ma dno w y = 0 (nóżki)
check(geom.legsHeight > 0, `dno drona na y = 0 (nozki ${geom.legsHeight} mm)`);

process.exit(failed ? 1 : 0);
