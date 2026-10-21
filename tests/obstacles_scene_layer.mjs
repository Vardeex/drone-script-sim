// Test warstwy sceny 3D w Node: prawdziwy three.js + atrapa DOM/canvasu.
import * as THREE from '../app/static/vendor/three.module.js';
import { register } from 'node:module';
import { pathToFileURL } from 'node:url';

const hookUrl = pathToFileURL(new URL('./three_loader.mjs', import.meta.url).pathname
  .replace(/^\/([A-Za-z]:)/, '$1')).href;
register(hookUrl);

// Minimalne atrapy DOM/Canvas dla createTextSprite (etykiety jako sprite'y).
if (typeof globalThis.window === 'undefined') {
  globalThis.window = { addEventListener() {}, removeEventListener() {} };
  globalThis.document = {
    createElement() {
      return { width: 0, height: 0, getContext: () => ({
        scale() {}, fillRect() {}, fillText() {}, measureText: () => ({ width: 10 }),
        set font(value) {}, set fillStyle(value) {}, set textAlign(value) {},
        set textBaseline(value) {},
      }) };
    },
  };
}

const stage = { add() {}, remove() {} };
const fakeDroneScene = {
  scene: stage,
  camera: new THREE.PerspectiveCamera(),
  controls: { enabled: true },
  renderer: { domElement: { addEventListener() {}, removeEventListener() {}, style: {} } },
};

const { createLayer } = await import('../app/static/js/features/obstacles/scene_layer.js');

const results = [];
const check = (name, fn) => {
  try {
    fn();
    results.push(`OK   ${name}`);
  } catch (err) {
    results.push(`FAIL ${name}: ${err && err.message}`);
    if (err && err.stack) results.push(err.stack.split('\n').slice(1, 4).join('\n'));
  }
};

let layer;
check('createLayer', () => { layer = createLayer({ scene: fakeDroneScene }); });
check('setScene (pusta scena)', () => layer.setScene({ obstacles: [] }));

const scene = {
  name: 'test',
  obstacles: [
    { id: 'a', kind: 'box', name: 'ściana', position: [100, 0, 80], size: [10, 400, 160], yaw_deg: 0 },
    { id: 'b', kind: 'cylinder', name: 'słup', position: [200, 50, 80], size: [30, 30, 150], yaw_deg: 0 },
    { id: 'c', kind: 'gate', name: 'bramka', position: [300, 0, 80], size: [120, 5, 120], opening: [90, 90], yaw_deg: 30 },
    { id: 'd', kind: 'plane', name: 'sufit', position: [0, 0, 250], size: [400, 400, 5], thickness: 5, yaw_deg: 0 },
  ],
};
check('setScene (4 rodzaje)', () => layer.setScene(scene));
check('setViewMode solid', () => layer.setViewMode('solid'));
check('setViewMode ghost', () => layer.setViewMode('ghost'));
check('setSelection', () => layer.setSelection('c'));
check('setLabels(false)', () => layer.setLabels(false));
check('setHighlightHits', () => layer.setHighlightHits(['a', 'b']));
check('setFindings', () => layer.setFindings([
  { level: 'collision', t: 1.0, position: [150, 0, 80] },
  { level: 'warning', t: 2.0, position: [200, 0, 80] },
  { level: 'gate', t: 3.0, position: [300, 0, 80] },
]));
check('setMarkersTime', () => layer.setMarkersTime(2.5));
check('setEditMode', () => layer.setEditMode(true, { onSelect() {}, onDrag() {} }));
check('tick', () => layer.tick());
check('setViewMode hidden', () => layer.setViewMode('hidden'));
check('dispose', () => layer.dispose());

console.log(results.join('\n'));
const failed = results.filter((line) => line.startsWith('FAIL'));
process.exitCode = failed.length ? 1 : 0;
