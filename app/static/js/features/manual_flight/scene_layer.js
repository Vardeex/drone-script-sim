// Warstwa sceny 3D funkcji "Lot ręczny" (punkt rozszerzeń nr 4).
//
// Rdzeń sceny nie wie nic o locie ręcznym: dostaje obiekt z metodami
//   setTrail(points)  - narysuj ślad lotu ([] = wyczyść),
//   tick(), dispose().
// Układ: telemetria w cm -> scena three.js w metrach, (x, y, z) -> (x, z, -y).

import * as THREE from 'three';

const M = 100;                       // 1 m = 100 cm
const MAX_POINTS = 4000;             // zabezpieczenie pamięci przy długim locie

/** Pozycja drona (cm) -> współrzędne sceny three.js (m). */
function toScenePoint(x, y, z) {
  return new THREE.Vector3(x / M, z / M, -y / M);
}

/**
 * Zbuduj warstwę śladu lotu ręcznego.
 * @param {{scene: object}} context  scena rdzenia (DroneScene - three.js)
 */
export function createLayer({ scene: droneScene } = {}) {
  const three = droneScene.scene;
  const root = new THREE.Group();
  root.name = 'manual-flight';
  three.add(root);

  const material = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true,
    opacity: 0.9 });
  const geometry = new THREE.BufferGeometry();
  const line = new THREE.Line(geometry, material);
  line.frustumCulled = false;
  root.add(line);

  let points = [];

  return {
    /** Ustaw ślad lotu (lista ``[x, y, z]`` w cm). */
    setTrail(next) {
      points = (next || []).slice(-MAX_POINTS).map((p) => toScenePoint(p[0], p[1], p[2]));
      const positions = new Float32Array(points.length * 3);
      points.forEach((point, index) => {
        positions[index * 3] = point.x;
        positions[index * 3 + 1] = point.y;
        positions[index * 3 + 2] = point.z;
      });
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      geometry.computeBoundingSphere();
      line.visible = points.length > 1;
      droneScene.requestRender?.();       // tryb lekki: rysuj po zmianie śladu
    },

    /** Liczba punktów śladu (diagnostyka/testy). */
    get trailLength() {
      return points.length;
    },

    tick() { /* ślad jest statyczny do następnego setTrail */ },

    dispose() {
      root.remove(line);
      geometry.dispose();
      material.dispose();
      three.remove(root);
    },
  };
}
