// Warstwa sceny 3D funkcji „Planer trasy” (punkt rozszerzeń nr 4).
// Rdzeń dostaje obiekt: setRoute, setSelection, setPreview, setPlaceMode,
// setDragMode, tick, dispose. Układ: cm -> m, (x, y, z) -> (x, z, -y).

import * as THREE from 'three';

const M = 100;
const LINE_COLOR = 0x38bdf8;
const PREVIEW_COLOR = 0x22c55e;
const SELECTED_COLOR = 0xfbbf24;

function toVec(x, y, z) {
  return new THREE.Vector3(x / M, z / M, -y / M);
}

function clear(group) {
  for (const child of group.children.slice()) {
    group.remove(child);
    child.traverse?.((node) => {
      node.geometry?.dispose?.();
      if (node.material) {
        [].concat(node.material).forEach((m) => {
          m.map?.dispose?.();
          m.dispose?.();
        });
      }
    });
  }
}

function labelSprite(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 96;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(13, 17, 23, .82)';
  ctx.fillRect(0, 0, 256, 96);
  ctx.font = '600 44px "Segoe UI", sans-serif';
  ctx.fillStyle = '#e2e8f0';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 48, 244);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false,
  }));
  sprite.scale.set(0.85, 0.32, 1);
  return sprite;
}

/** Zbuduj warstwę planera (kontekst rdzenia: `{ scene }`). */
export function createLayer({ scene: droneScene } = {}) {
  const three = droneScene.scene;
  const root = new THREE.Group();
  root.name = 'route-planner';
  three.add(root);
  const markers = new THREE.Group();
  const lines = new THREE.Group();
  const preview = new THREE.Group();
  root.add(markers, lines, preview);

  const state = { route: null, selection: null, place: false, drag: false,
                  callbacks: {}, dragIndex: null, dragHeight: false };
  const raycaster = new THREE.Raycaster();
  const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const canvas = droneScene.renderer.domElement;

  function defaultHeight() {
    const points = state.route?.points || [];
    return points.length ? points[points.length - 1].z : 100;
  }

  function drawMarkers() {
    clear(markers);
    (state.route?.points || []).forEach((point, index) => {
      const selected = state.selection === index;
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(selected ? 0.11 : 0.085, 16, 10),
        new THREE.MeshStandardMaterial({
          color: selected ? SELECTED_COLOR : LINE_COLOR, roughness: 0.4,
        }),
      );
      sphere.position.copy(toVec(point.x, point.y, point.z));
      sphere.userData.index = index;
      markers.add(sphere);

      const drop = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          toVec(point.x, point.y, point.z), toVec(point.x, point.y, 0),
        ]),
        new THREE.LineDashedMaterial({
          color: LINE_COLOR, dashSize: 0.08, gapSize: 0.06,
          transparent: true, opacity: 0.45,
        }),
      );
      drop.computeLineDistances();
      markers.add(drop);

      const label = labelSprite(`${index + 1} · ${Math.round(point.z)}`);
      label.position.copy(toVec(point.x, point.y, point.z + 22));
      markers.add(label);
    });
  }

  function drawLine() {
    clear(lines);
    const points = state.route?.points || [];
    if (points.length < 2) return;
    lines.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points.map((p) => toVec(p.x, p.y, p.z))),
      new THREE.LineBasicMaterial({ color: LINE_COLOR }),
    ));

  function redraw() {
    drawLine();
    drawMarkers();
  }

  function rayAt(event) {
    const rect = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    ), droneScene.camera);
    return raycaster;
  }

  function markerAt(event) {
    const hits = rayAt(event).intersectObjects(markers.children, false);
    const hit = hits.find((item) => typeof item.object.userData.index === 'number');
    return hit ? hit.object.userData.index : null;
  }

  function groundAt(event) {
    const point = new THREE.Vector3();
    if (!rayAt(event).ray.intersectPlane(ground, point)) return null;
    return { x: point.x * M, y: -point.z * M };
  }

  function updateCursor() {
    if (state.dragIndex !== null) {
      canvas.style.cursor = state.dragHeight ? 'ns-resize' : 'grabbing';
    } else if (state.drag) {
      canvas.style.cursor = 'grab';
    } else {
      canvas.style.cursor = state.place ? 'crosshair' : '';
    }
  }

  function onDown(event) {
    if (event.button !== 0) return;
    const index = markerAt(event);
    if (state.drag && index !== null) {
      state.dragIndex = index;
      state.dragHeight = event.shiftKey;
      updateCursor();
      state.callbacks.onSelect?.(index);
      event.preventDefault();
      return;
    }
    if (state.place && index === null) {
      const spot = groundAt(event);
      if (spot) {
        state.callbacks.onAdd?.({ x: spot.x, y: spot.y, z: defaultHeight() });
        event.preventDefault();
      }
    }
  }

  function onMove(event) {
    if (state.dragIndex === null) return;
    if (state.dragHeight) {
      state.callbacks.onMove?.(state.dragIndex, { dz: -(event.movementY ?? 0) });
    } else {
      const spot = groundAt(event);
      if (spot) state.callbacks.onMove?.(state.dragIndex, { x: spot.x, y: spot.y });
    }
    event.preventDefault();
  }

  function onUp() {
    if (state.dragIndex === null) return;
    state.dragIndex = null;
    state.dragHeight = false;
    updateCursor();
  }

  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);

  return {
    setRoute(route) {
      state.route = route || null;
      redraw();
    },
    setSelection(index) {
      state.selection = Number.isInteger(index) ? index : null;
      drawMarkers();
    },
    setPreview(points = []) {
      clear(preview);
      if (!points.length) return;
      preview.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(points.map((p) => toVec(p.x, p.y, p.z))),
        new THREE.LineBasicMaterial({ color: PREVIEW_COLOR, transparent: true, opacity: 0.8 }),
      ));
      const geometry = new THREE.SphereGeometry(0.05, 8, 6);
      const material = new THREE.MeshStandardMaterial({ color: PREVIEW_COLOR });
      for (const point of points) {
        const dot = new THREE.Mesh(geometry, material);
        dot.position.copy(toVec(point.x, point.y, point.z));
        preview.add(dot);
      }
    },
    setPlaceMode(enabled, callbacks = {}) {
      state.place = Boolean(enabled);
      state.callbacks = { ...state.callbacks, ...callbacks };
      updateCursor();
    },
    setDragMode(enabled, callbacks = {}) {
      state.drag = Boolean(enabled);
      state.callbacks = { ...state.callbacks, ...callbacks };
      updateCursor();
    },
    tick() {},
    dispose() {
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      three.remove(root);
      clear(root);
    },
  };
}
}
