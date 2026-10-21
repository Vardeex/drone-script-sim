// Warstwa sceny 3D funkcji "Przeszkody 3D" (punkt rozszerzeń nr 4).
//
// Rdzeń sceny nie wie nic o przeszkodach: dostaje obiekt z metodami
//   setScene(sceneJson)             - narysuj scenę (null = wyczyść),
//   setSelection(id)                - podświetl wybraną przeszkodę,
//   setViewMode("solid"|"ghost"|"hidden"),
//   setFindings(findings)           - znaczniki kolizji/ostrzeżeń/bramek na trasie,
//   setMarkersTime(t)               - podkreśl zdarzenia do chwili t,
//   setEditMode(enabled, callbacks) - przeciąganie przeszkód po podłożu,
//   setLabels(enabled), setHighlightHits(ids), tick(), dispose().
// Układ: telemetria w cm -> scena three.js w metrach, (x, y, z) -> (x, z, -y).

import * as THREE from 'three';

const M = 100;                       // 1 m = 100 cm
const KIND_COLOR = { box: 0x60a5fa, cylinder: 0x34d399, gate: 0xfbbf24, plane: 0x94a3b8 };
const LEVEL_COLOR = { collision: 0xef4444, warning: 0xf59e0b, gate: 0x22c55e };
const LEVEL_LABEL = { collision: 'Kolizja', warning: 'Zbliżenie', gate: 'Bramka' };

/** Pozycja drona (cm) -> współrzędne sceny three.js (m). */
export function toScenePoint(x, y, z) {
  return new THREE.Vector3(x / M, z / M, -y / M);
}

function kindMaterial(kind, opacity) {
  return new THREE.MeshStandardMaterial({
    color: KIND_COLOR[kind] || 0x60a5fa,
    transparent: true,
    opacity,
    roughness: 0.55,
    metalness: 0.05,
    depthWrite: opacity >= 0.99,
    side: THREE.DoubleSide,
  });
}

function makeTextSprite(text, color = '#e2e8f0', width = 0.9) {
  const scale = 2;
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  canvas.width = 256 * scale;
  canvas.height = 64 * scale;
  ctx.scale(scale, scale);
  ctx.fillStyle = 'rgba(13, 17, 23, .78)';
  ctx.fillRect(0, 0, 256, 64);
  ctx.font = '600 26px "Segoe UI", sans-serif';
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 32, 240);
  const texture = new THREE.CanvasTexture(canvas);
  texture.anisotropy = 4;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture, transparent: true, depthTest: false,
  }));
  sprite.scale.set(width, width / 4, 1);
  return sprite;
}

/**
 * Usuń dzieci grupy i zwolnij ich zasoby GPU.
 */
function disposeGroup(group) {
  for (const child of group.children.slice()) {
    group.remove(child);
    child.traverse?.((node) => {
      node.geometry?.dispose?.();
      if (node.material) {
        [].concat(node.material).forEach((material) => {
          material.map?.dispose?.();
          material.dispose?.();
        });
      }
    });
  }
}

/**
 * Zbuduj warstwę przeszkód.
 * @param {{scene: object}} context  scena rdzenia (DroneScene - three.js)
 */
export function createLayer({ scene: droneScene } = {}) {
  const three = droneScene.scene;
  const root = new THREE.Group();
  root.name = 'obstacles';
  three.add(root);

  const pickGroup = new THREE.Group();
  const markerGroup = new THREE.Group();
  root.add(pickGroup, markerGroup);

  const state = {
    scene: null,
    viewMode: 'ghost',
    selection: null,
    hitIds: new Set(),
    editMode: false,
    callbacks: {},
    markers: [],
    t: 0,
    labels: true,
  };

  const raycaster = new THREE.Raycaster();
  const dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const drag = { id: null, offset: new THREE.Vector3(), active: false };
  const canvas = droneScene.renderer.domElement;

  function wrap(mesh) {
    const group = new THREE.Group();
    group.add(mesh);
    return group;
  }

  function buildGate(obstacle, material) {
    const [w, d, h] = obstacle.size;
    const [ow, oh] = obstacle.opening || [50, 50];
    const group = new THREE.Group();
    const thickness = Math.max((h - oh) / 2, 0.1);
    const sideWidth = Math.max((w - ow) / 2, 0.1);
    const parts = [
      [sideWidth, d, h, -(ow + sideWidth) / 2, 0],
      [sideWidth, d, h, (ow + sideWidth) / 2, 0],
      [ow, d, thickness, 0, (oh + thickness) / 2],
      [ow, d, thickness, 0, -(oh + thickness) / 2],
    ];
    for (const [sx, sy, sz, ox, oz] of parts) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(sx / M, sz / M, sy / M),
        material.clone());
      mesh.position.set(ox / M, oz / M, 0);
      group.add(mesh);
    }
    return group;
  }

  function buildMesh(obstacle, material) {
    const [w, d, h] = obstacle.size;
    if (obstacle.kind === 'cylinder') {
      return wrap(new THREE.Mesh(
        new THREE.CylinderGeometry(w / 2 / M, w / 2 / M, h / M, 24), material));
    }
    if (obstacle.kind === 'gate') return buildGate(obstacle, material);
    if (obstacle.kind === 'plane') {
      const thickness = Math.max(obstacle.thickness || 5, 1);
      return wrap(new THREE.Mesh(new THREE.BoxGeometry(w / M, thickness / M, d / M), material));
    }
    return wrap(new THREE.Mesh(new THREE.BoxGeometry(w / M, h / M, d / M), material));
  }

  function addEdges(group, color, opacity) {
    group.traverse((node) => {
      if (!node.isMesh) return;
      node.add(new THREE.LineSegments(
        new THREE.EdgesGeometry(node.geometry),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity })));
    });
  }

  function rebuild() {
    disposeGroup(pickGroup);
    if (!state.scene || state.viewMode === 'hidden') {
      rebuildMarkers();
      return;
    }
    const opacity = state.viewMode === 'solid' ? 1.0 : 0.38;
    for (const obstacle of state.scene.obstacles || []) {
      const base = new THREE.Group();
      const selected = state.selection === obstacle.id;
      const body = buildMesh(obstacle, kindMaterial(obstacle.kind, opacity));
      base.add(body);
      addEdges(body, selected ? 0x38bdf8 : 0x0f172a, selected ? 1 : 0.5);
      if (state.hitIds.has(obstacle.id)) {
        base.traverse((node) => {
          if (node.isMesh && node.material.color) node.material.color.setHex(0xef4444);
        });
      }
      const [x, y, z] = obstacle.position;
      base.position.set(x / M, z / M, -y / M);
      base.rotation.y = -THREE.MathUtils.degToRad(obstacle.yaw_deg || 0);
      base.userData = { obstacleId: obstacle.id, obstacle };
      if (state.labels) {
        const label = makeTextSprite(obstacle.name || obstacle.kind, '#93c5fd', 1.1);
        label.position.set(0, obstacle.size[2] / M / 2 + 0.14, 0);
        base.add(label);
      }
      pickGroup.add(base);
    }
    rebuildMarkers();
  }

  function rebuildMarkers() {
    disposeGroup(markerGroup);
    for (const marker of state.markers) {
      const color = LEVEL_COLOR[marker.level] || 0x94a3b8;
      const position = toScenePoint(...(marker.position || [0, 0, 0]));
      const lit = marker.t <= state.t + 1e-6;
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(marker.level === 'gate' ? 0.05 : 0.065, 16, 12),
        new THREE.MeshBasicMaterial({ color, transparent: true,
          opacity: lit ? 1 : 0.28, depthTest: false }));
      sphere.position.copy(position);
      sphere.renderOrder = 10;
      markerGroup.add(sphere);
      const label = makeTextSprite(LEVEL_LABEL[marker.level] || marker.level,
        `#${color.toString(16).padStart(6, '0')}`, 1.0);
      label.position.copy(position).add(new THREE.Vector3(0, 0.17, 0));
      label.material.opacity = lit ? 1 : 0.3;
      markerGroup.add(label);
    }
  }
  function pickObstacle(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, droneScene.camera);
    for (const hit of raycaster.intersectObjects(pickGroup.children, true)) {
      let node = hit.object;
      while (node && !node.userData?.obstacleId) node = node.parent;
      if (node?.userData?.obstacleId) return node;
    }
    return null;
  }

  function pointerRay(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, droneScene.camera);
    const point = new THREE.Vector3();
    return raycaster.ray.intersectPlane(dragPlane, point) ? point : null;
  }

  function onPointerDown(event) {
    if (!state.editMode || event.button !== 0) return;
    const target = pickObstacle(event.clientX, event.clientY);
    if (!target) return;
    const obstacle = target.userData.obstacle;
    state.callbacks.onSelect?.(obstacle.id);
    if (obstacle.kind === 'plane') return;      // sufitu nie przesuwamy po podłożu
    drag.id = obstacle.id;
    drag.active = true;
    const point = pointerRay(event.clientX, event.clientY);
    if (point) drag.offset.copy(target.position).sub(point);
    droneScene.controls.enabled = false;
    canvas.style.cursor = 'grabbing';
    event.preventDefault();
    event.stopPropagation();
  }

  function onPointerMove(event) {
    if (!drag.active) {
      if (state.editMode) {
        canvas.style.cursor = pickObstacle(event.clientX, event.clientY) ? 'grab' : '';
      }
      return;
    }
    const point = pointerRay(event.clientX, event.clientY);
    if (!point) return;
    point.add(drag.offset);
    const target = pickGroup.children.find((c) => c.userData.obstacleId === drag.id);
    if (!target) return;
    target.position.copy(point);
    state.callbacks.onDrag?.(drag.id, point.x * M, -point.z * M);
  }

  function onPointerUp() {
    if (!drag.active) return;
    drag.active = false;
    drag.id = null;
    droneScene.controls.enabled = true;
    canvas.style.cursor = state.editMode ? 'grab' : '';
    state.callbacks.onDragEnd?.();
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);

  return {
    /** Narysuj scenę (format JSON sceny) lub wyczyść (null). */
    setScene(sceneJson) {
      state.scene = sceneJson;
      state.hitIds.clear();
      rebuild();
    },
    /** Podświetl wybraną przeszkodę. */
    setSelection(id) {
      if (state.selection === id) return;
      state.selection = id;
      rebuild();
    },
    /** Tryb widoku: solid | ghost | hidden. */
    setViewMode(mode) {
      state.viewMode = mode || 'ghost';
      rebuild();
    },
    /** Znaczniki zdarzeń (kolizje, ostrzeżenia, bramki) na trasie. */
    setFindings(findings) {
      state.markers = findings || [];
      rebuildMarkers();
    },
    /** Podkreśl znaczniki zdarzeń do chwili t (sekundy). */
    setMarkersTime(t) {
      state.t = Number(t) || 0;
      rebuildMarkers();
    },
    /** Tryb edycji: przeciąganie przeszkód po podłożu. */
    setEditMode(enabled, callbacks = {}) {
      state.editMode = Boolean(enabled);
      state.callbacks = callbacks;
      if (!state.editMode) onPointerUp();
      canvas.style.cursor = state.editMode ? 'grab' : '';
    },
    /** Włącz/wyłącz etykiety nazw przeszkód. */
    setLabels(enabled) {
      state.labels = Boolean(enabled);
      rebuild();
    },
    /** Identyfikatory przeszkód do oznaczenia kolorem błędu (podgląd kolizji). */
    setHighlightHits(ids = []) {
      state.hitIds = new Set(ids);
      rebuild();
    },
    /** Wywoływane przy każdej klatce (na razie nic nie robi). */
    tick() {},
    /** Usuń warstwę ze sceny. */
    dispose() {
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      disposeGroup(markerGroup);
      disposeGroup(pickGroup);
      three.remove(root);
    },
  };
}

