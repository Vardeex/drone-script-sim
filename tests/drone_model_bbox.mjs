// Test modelu drona Tello: obrys 98 x 92,5 x 41 mm (tolerancja +-3 mm) i warunki
// geometryczne z zadania (korpus <= 50 mm, smigla nad korpusem, oslony koncentryczne).
//
// Wszystko liczone z parametrow app/static/js/drone_model.js (TELLO_GEOMETRY_MM) tak,
// jak buduje model. Uruchomienie: node tests/drone_model_bbox.mjs

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '..', 'app', 'static', 'js', 'drone_model.js'), 'utf8');

/** Wyciągnij liczby z bloku ``export const NAME = {...};``. */
function numbers(name) {
  const block = source.match(new RegExp(`export const ${name} = \\{([^}]*)\\}`));
  if (!block) throw new Error(`Brak ${name} w drone_model.js`);
  const out = {};
  for (const m of block[1].matchAll(/([A-Za-z][A-Za-z0-9]*): +([0-9.]+)/g)) out[m[1]] = Number(m[2]);
  return out;
}

const g = numbers('TELLO_GEOMETRY_MM');
const outline = numbers('TELLO_OUTLINE_MM');

// komplet pól wymaganych przez createTello - zabezpieczenie przed cichym usunięciem
const REQUIRED = [
  'bodyLength', 'bodyWidth', 'bodyHeight', 'bodyRadius', 'bodyZ',
  'cameraDiameter', 'cameraLength',
  'motorX', 'motorY', 'motorDiameter', 'motorZ1', 'motorZ2',
  'ringDiameter', 'ringZ1', 'ringZ2', 'legDiameter', 'legZ2',
  'armDiameter', 'armRootX', 'armRootY', 'armZ',
  'shaftDiameter', 'shaftZ1', 'shaftZ2',
  'propZ1', 'propZ2', 'propDiameter', 'hubDiameter', 'hubZ2',
  'guardRadius', 'guardTube', 'guardZ', 'guardGapDeg',
  'guardSpokeRadius', 'guardSpokeZ', 'guardSpokeAngleDeg',
];

let failed = 0;
const check = (ok, text) => {
  if (!ok) failed += 1;
  console.log(`${ok ? 'OK  ' : 'FAIL'} ${text}`);
};

const missing = REQUIRED.filter((key) => typeof g[key] !== 'number');
check(missing.length === 0,
  `komplet ${REQUIRED.length} pol geometrii${missing.length ? ` (brak: ${missing.join(', ')})` : ''}`);

const propHalf = g.propDiameter / 2;                    // 19 mm
const guardOuter = g.guardRadius + g.guardTube / 2;     // 21 + 1,25 = 22,25 mm

// obrys: oslony sa najdalszym elementem w X i Y, smiglo w Z (gorna plaszczyzna)
const measured = {
  length: 2 * (g.motorX + guardOuter),
  width: 2 * (g.motorY + guardOuter),
  height: g.propZ2,
};
console.log(`model: ${measured.length.toFixed(1)} x ${measured.width.toFixed(1)} x ` +
  `${measured.height.toFixed(1)} mm (osie zadania: x x y x z)`);

const tolerance = 3.0; // mm
for (const [name, key, target] of [
  ['dlugosc', 'length', outline.length],
  ['szerokosc', 'width', outline.width],
  ['wysokosc', 'height', outline.height],
]) {
  const diff = Math.abs(measured[key] - target);
  check(diff <= tolerance,
    `${name}: ${measured[key].toFixed(2)} mm (cel ${target} mm, odchylka ${diff.toFixed(2)} mm)`);
}

// korpus krotki wzgledem calego drona
check(g.bodyLength <= 50, `korpus ${g.bodyLength} mm <= 50 mm`);
check(g.bodyWidth <= 50 && g.bodyHeight <= 50,
  `korpus w przekroju ${g.bodyWidth} x ${g.bodyHeight} mm`);

// smigla sa wyzej niz korpus (korpus konczy sie na bodyZ + bodyHeight = 28 mm)
const bodyTop = g.bodyZ + g.bodyHeight;
check(g.propZ1 > bodyTop,
  `smigla nad korpusem (smiglo od ${g.propZ1} mm, korpus do ${bodyTop} mm)`);
check(g.shaftZ2 === g.propZ1,
  `walek podtrzymuje smiglo (walek do ${g.shaftZ2} mm, smiglo od ${g.propZ1} mm)`);

// oslony: tuz pod smiglami, ale nad korpusem i nad silnikami
check(g.guardZ < g.propZ1 && g.guardZ - g.guardTube / 2 > bodyTop,
  `oslony (${g.guardZ} mm) nad korpusem i pod smiglami`);
check(g.guardRadius >= propHalf,
  `oslona obejmuje smiglo (R ${g.guardRadius} mm >= ${propHalf} mm)`);
check(g.guardRadius + g.guardTube / 2 > propHalf,
  `luk oslony poza koncowka lopaty (${guardOuter} mm > ${propHalf} mm)`);
const guardArcDeg = 360 - g.guardGapDeg;
check(guardArcDeg >= 270 && guardArcDeg <= 300,
  `luk oslony ${guardArcDeg.toFixed(0)}° (przerwa ${g.guardGapDeg}°, luk wymagany 270-300°)`);

// sasiednie oslony sie nie stykaja, ale przerwy sa waskie (koncentrycznosc z silnikiem)
const gapX = 2 * g.motorX - 2 * guardOuter;
const gapY = 2 * g.motorY - 2 * guardOuter;
check(gapX > 0 && gapY > 0,
  `oslony nie koliduja (przerwa ${gapX.toFixed(1)} mm w x, ${gapY.toFixed(1)} mm w y)`);
check(gapX < g.propDiameter && gapY > 0 && gapY < g.propDiameter,
  `oslony blisko siebie (przerwy w granicach tarczy smigla)`);

// sasiednie smigla sie nie przecinaja
const propGapX = 2 * g.motorX - g.propDiameter;
const propGapY = 2 * g.motorY - g.propDiameter;
check(propGapX > 0 && propGapY > 0,
  `smigla nie koliduja (przerwa ${propGapX.toFixed(1)} mm w x, ${propGapY.toFixed(1)} mm w y)`);

// smigla moga zachodzic nad naroznikami korpusu w rzucie z gory - mierzymy to,
// ale nie moze to byc kolizja, bo smigla sa wyzej niz korpus
const overlapX = g.bodyLength / 2 + propHalf - g.motorX;
const overlapY = g.bodyWidth / 2 + propHalf - g.motorY;
console.log(`INFO zachodzenie smigla nad korpusem w rzucie: x ${overlapX.toFixed(1)} mm, ` +
  `y ${overlapY.toFixed(1)} mm (dozwolone - smigla ${g.propZ1} mm, korpus do ${bodyTop} mm)`);

// dno drona na ziemi: nozki od z = 0
check(g.legZ2 > 0 && g.motorZ1 === g.legZ2,
  `nozki ${g.legZ2} mm pod silnikami (dno drona na z = 0)`);

// ramie laczy korpus z osia silnika
const armLen = Math.hypot(g.motorX - g.armRootX, g.motorY - g.armRootY);
check(armLen > 0 && g.armDiameter < g.motorDiameter,
  `ramie ${armLen.toFixed(1)} mm, ø${g.armDiameter} mm (ciensze od silnika)`);

// szprycha: od silnika (r = guardSpokeRadius) w gore do luku (guardZ), pod katem
const spokeLen = Math.hypot(g.guardRadius - g.guardSpokeRadius, g.guardZ - g.guardSpokeZ);
check(spokeLen > 0 && g.guardSpokeRadius < g.guardRadius,
  `szprycha ${spokeLen.toFixed(1)} mm (r ${g.guardSpokeRadius} -> ${g.guardRadius}, z ` +
  `${g.guardSpokeZ} -> ${g.guardZ})`);

console.log(failed ? `${failed} kontrol(i) nie przeszlo` : 'wszystkie kontrole OK');
process.exit(failed ? 1 : 0);
