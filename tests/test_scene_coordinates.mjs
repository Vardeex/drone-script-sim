// Test transformacji współrzędnych sceny 3D (niezależny od symulatora i biblioteki).
//
// Układ projektu: telemetria (x przód, y lewo, z góra) trafia do sceny three.js
// jako (x, z, -y). Kamera patrząca od TYŁU drona (wzdłuż +X, Y w górę) ma oś
// "prawo ekranu" = cross(forward, up) = +Z. Prawa strona drona (−y) musi wypaść
// po prawej stronie ekranu, inaczej obraz lotu jest lustrzany.
//
// Uruchomienie: node tests/test_scene_coordinates.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const timeline = readFileSync(join(here, '..', 'app', 'static', 'js', 'timeline.js'), 'utf8');

let failed = 0;
const check = (ok, text) => {
  if (!ok) failed += 1;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${text}`);
};

// toScene z app/static/js/timeline.js - musi istnieć i mapować y -> -z
const match = timeline.match(/export function toScene\(pos\) \{\s*return \{([^}]*)\};/);
check(Boolean(match), 'toScene istnieje w timeline.js');
const body = match ? match[1] : '';
const toScene = (pos) => ({ x: pos.x, y: pos.z, z: -pos.y });
check(/x: pos\.x/.test(body), 'toScene: składowa x = x (przód)');
check(/y: pos\.z/.test(body), 'toScene: składowa y = z (góra)');
check(/z: -pos\.y/.test(body), 'toScene: składowa z = -y (lewo -> -z)');

// kamera od tyłu: patrzy wzdłuż +X, góra = +Y  => prawo ekranu = cross(fwd, up)
const forward = [1, 0, 0];
const up = [0, 1, 0];
const screenRight = [
  forward[1] * up[2] - forward[2] * up[1],
  forward[2] * up[0] - forward[0] * up[2],
  forward[0] * up[1] - forward[1] * up[0],
];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const onScreenRight = (telemetryPoint) => {
  const p = toScene(telemetryPoint);
  return dot([p.x, p.y, p.z], screenRight);
};

// prawa strona drona w układzie lotu to -y
check(onScreenRight({ x: 0, y: -10, z: 0 }) > 0,
  'punkt po prawej stronie drona (−y) rysowany po prawej ekranu');
check(onScreenRight({ x: 0, y: 10, z: 0 }) < 0,
  'punkt po lewej stronie drona (+y) rysowany po lewej ekranu');
// góra i przód mają sensowny kierunek
check(onScreenRight({ x: 0, y: 0, z: 10 }) === 0,
  'wysokość (z) nie przesuwa punktu na boki');
check(toScene({ x: 10, y: 0, z: 0 }).x === 10,
  'przód drona (+x) zostaje na osi przód w scenie');

console.log(failed ? `${failed} kontrol(i) nie przeszlo` : 'wszystkie kontrole OK');
process.exit(failed ? 1 : 0);
