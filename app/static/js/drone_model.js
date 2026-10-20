// Model drona 3D z prymitywów three.js (bez zewnętrznych plików modeli).
//
// Adapter modeli: każdy model to funkcja (options) => { group, rotors, size }.
// Dzięki temu w przyszłości można dodać modele innych dronów, nie zmieniając sceny.
//
// Układ osi modelu (układ drona):
//   +X - przód, +Y - w górę, +Z - prawo drona,
//   dno drona w y = 0, środek obrotu = środek geometryczny (y = wysokość/2).
// Jednostki: jednostki sceny three.js (1 = 1 m).

import * as THREE from 'three';

//: DJI Ryze Tello EDU - wymiary zewnętrzne obrysu (mm); obrys jest nadrzędny
export const TELLO_OUTLINE_MM = { length: 98.0, width: 92.5, height: 41.0, weight_g: 87 };

//: Geometria modelu (mm, układ zadania: x = przód, y = lewo, z = góra).
//: Współrzędne są ustalone - test tests/drone_model_bbox.mjs sprawdza je liczbowo.
export const TELLO_GEOMETRY_MM = {
  // korpus
  bodyLength: 45.0,        // x: -22,5..22,5
  bodyWidth: 26.0,         // y: -13..13
  bodyHeight: 20.0,        // z: 8..28
  bodyRadius: 5.0,
  bodyZ: 8.0,
  // kamera
  cameraDiameter: 6.0,
  cameraLength: 2.0,
  // silniki (osie w punktach +-27, +-24)
  motorX: 27.0,
  motorY: 24.0,
  motorDiameter: 8.0,
  motorZ1: 6.0,
  motorZ2: 26.0,
  ringDiameter: 8.6,
  ringZ1: 22.0,
  ringZ2: 25.0,
  legDiameter: 3.0,
  legZ2: 6.0,
  // ramiona: od korpusu (+-16, +-11, 16) do osi silnika (16)
  armDiameter: 4.0,
  armRootX: 16.0,
  armRootY: 11.0,
  armZ: 16.0,
  // wałek i śmigło
  shaftDiameter: 2.5,
  shaftZ1: 26.0,
  shaftZ2: 37.0,
  propZ1: 37.0,
  propZ2: 38.5,
  propDiameter: 38.0,
  hubDiameter: 5.0,
  hubZ2: 39.0,
  // osłony
  guardRadius: 21.0,
  guardTube: 2.5,
  guardZ: 34.0,
  guardGapDeg: 80.0,
  guardSpokeRadius: 4.0,
  guardSpokeZ: 20.0,
  guardSpokeAngleDeg: 55.0,
};

//: promień śmigła (mm) i promień łuku, potrzebne w createTello
const PROP_RADIUS_MM = 19.0;
const GUARD_RADIUS_MM = TELLO_GEOMETRY_MM.guardRadius;
const GUARD_Z_MM = TELLO_GEOMETRY_MM.guardZ;
const GUARD_GAP_DEG = TELLO_GEOMETRY_MM.guardGapDeg;
//: kolor akcentu przednich osłon (stonowany pomarańcz/czerwień)
export const ACCENT_COLOR = 0x9a3b2a;


const mm = (value) => value / 1000;
const DEG = Math.PI / 180;

function materials(accentHex) {
  return {
    // korpus i ramiona: grafit, lekko błyszczący (bez osobnej pokrywy)
    shell: new THREE.MeshStandardMaterial({ color: 0x5b626c, roughness: 0.55, metalness: 0.35 }),
    // nóżki, piasty: matowy grafit
    dark: new THREE.MeshStandardMaterial({ color: 0x3c424a, roughness: 0.7, metalness: 0.25 }),
    // śmigła i silniki
    prop: new THREE.MeshStandardMaterial({ color: 0x1b1e22, roughness: 0.45, metalness: 0.15 }),
    motor: new THREE.MeshStandardMaterial({ color: 0x23262b, roughness: 0.5, metalness: 0.45 }),
    chrome: new THREE.MeshStandardMaterial({ color: 0xc9d2da, roughness: 0.18, metalness: 0.95 }),
    accent: new THREE.MeshStandardMaterial({
      color: accentHex, roughness: 0.5, metalness: 0.3,
      emissive: accentHex, emissiveIntensity: 0.04,
    }),
    lens: new THREE.MeshStandardMaterial({
      color: 0x0b0e12, roughness: 0.12, metalness: 0.95,
    }),
  };
}

/** Bounding box modelu - z wierzchołków geometrii (działa też po scaleniu siatek). */
export function measure(group) {
  group.updateMatrixWorld(true);
  const box = new THREE.Box3();
  const point = new THREE.Vector3();
  const stack = [group];
  while (stack.length) {
    const node = stack.pop();
    if (node.isMesh && node.geometry) {
      const position = node.geometry.attributes.position;
      const count = position ? position.count : 0;
      for (let i = 0; i < count; i += 1) {
        point.fromBufferAttribute(position, i).applyMatrix4(node.matrixWorld);
        box.expandByPoint(point);
      }
    }
    for (let i = 0; i < node.children.length; i += 1) stack.push(node.children[i]);
  }
  return box.getSize(new THREE.Vector3());
}

/**
 * Zbuduj model drona Tello z dokładnie zadanych współrzędnych (mm).
 *
 * Układ zadania: x = przód, y = lewo, z = góra, ziemia z = 0, środek drona (0, 0).
 * Osie sceny three.js: X = x (przód), Y = z (góra), Z = -y (prawo drona).
 *
 * @param {object} [options]
 * @param {boolean} [options.guards=true] - osłony śmigieł (łuki)
 * @param {number} [options.accent] - kolor akcentu przednich osłon
 * @returns {{group: THREE.Group, rotors: THREE.Object3D[], size: THREE.Vector3}}
 */
export function createTello({ guards = true, accent = ACCENT_COLOR } = {}) {
  const mats = materials(accent);
  const group = new THREE.Group();
  group.name = 'tello';
  const statics = [];
  const rotors = [];

  // pozycja w układzie zadania (x, y, z w mm) -> scena (metry)
  const sx = (x) => mm(x);
  const sy = (z) => mm(z);       // góra
  const sz = (y) => -mm(y);      // lewo -> -Z

  const mesh = (geometry, material, x, y, z) => {
    const item = new THREE.Mesh(geometry, material);
    item.position.set(sx(x), sy(z), sz(y));
    statics.push(item);
    return item;
  };

  /** Cylinder pionowy (oś z) od z1 do z2 w punkcie (x, y). */
  const upright = (radius, x, y, z1, z2, material, segments = 16) => mesh(
    new THREE.CylinderGeometry(mm(radius), mm(radius), mm(z2 - z1), segments, 1),
    material, x, y, (z1 + z2) / 2,
  );

  /** Cylinder między punktami (x, y, z) - ramiona i szprychy. */
  const rod = (radius, from, to, material) => {
    const a = new THREE.Vector3(sx(from[0]), sy(from[2]), sz(from[1]));
    const b = new THREE.Vector3(sx(to[0]), sy(to[2]), sz(to[1]));
    const item = new THREE.Mesh(
      new THREE.CylinderGeometry(mm(radius), mm(radius), a.distanceTo(b), 10, 1), material);
    item.position.copy(a).lerp(b, 0.5);
    orientAlong(item, new THREE.Vector3().subVectors(b, a));
    statics.push(item);
    return item;
  };

  // --- 1. korpus: zaokrąglony prostopadłościan 45 x 26 x 20, z 8..28, r 5 ---
  mesh(roundedBoxGeometry(mm(45), mm(20), mm(26), mm(5)), mats.shell, 0, 0, 18);

  // kamera: walec ø6 x 2, oś wzdłuż x, środek (22, 0, 18)
  const camera = mesh(new THREE.CylinderGeometry(mm(3), mm(3), mm(2), 20, 1),
    mats.lens, 22, 0, 18);
  camera.rotation.z = Math.PI / 2;
// --- 2..5. silniki, ramiona, wałki, śmigła, osłony ---
  const MOTOR_XY = [[27, -24], [27, 24], [-27, 24], [-27, -24]];   // PF, PB, LB, LF
  const ARM_ROOT = [[16, -11], [16, 11], [-16, 11], [-16, -11]];

  /** Jedna łopata: zwężająca się, płaska, z zaokrągloną końcówką (lokalnie 0..38 mm w X). */
  const blade = () => {
    const L = PROP_RADIUS_MM;                 // 19 mm
    const shape = new THREE.Shape();
    shape.moveTo(mm(1.2), mm(2.5));
    shape.lineTo(mm(L - 3), mm(1.5));
    shape.quadraticCurveTo(mm(L), mm(1.5), mm(L), 0);
    shape.quadraticCurveTo(mm(L), mm(-1.5), mm(L - 3), mm(-1.5));
    shape.lineTo(mm(1.2), mm(-2.5));
    shape.closePath();
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: mm(1.5), bevelEnabled: false, curveSegments: 6,
    });
    // wyciągnięcie po +Z (grubość 1,5 mm) -> obracamy tak, by grubość była w pionie (Y);
    // dolna płaszczyzna łopaty leży wtedy na lokalnym y = -1,5 mm - wyrównujemy do y = 0
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, mm(0.0), 0);
    return new THREE.Mesh(geometry, mats.prop);
  };

  for (let i = 0; i < MOTOR_XY.length; i += 1) {
    const mx = MOTOR_XY[i][0];
    const my = MOTOR_XY[i][1];
    const ax = ARM_ROOT[i][0];
    const ay = ARM_ROOT[i][1];
    const front = mx > 0;

    // ramię: ø4 od (ax, ay, 16) do osi silnika (mx, my, 16)
    rod(2, [ax, ay, 16], [mx, my, 16], mats.shell);

    // nóżka ø3, z 0..6 pod silnikiem
    upright(1.5, mx, my, 0, 6, mats.dark, 10);

    // silnik ø8, z 6..26 + srebrny pierścień ø8,6, z 22..25
    upright(4, mx, my, 6, 26, mats.motor, 18);
    upright(4.3, mx, my, 22, 25, mats.chrome, 18);

    // wałek ø2,5, z 26..37 (śmigło stoi nad korpusem) + piasta ø5 x 2
    upright(1.25, mx, my, 26, 37, mats.chrome, 12);
    upright(2.5, mx, my, 37, 39, mats.dark, 12);

    // śmigło: 2 łopaty, średnica 38, z 37..38,5
    const rotor = new THREE.Group();
    rotor.position.set(sx(mx), sy(37), sz(my));
    for (const back of [0, 1]) {
      const item = blade();
      if (back) item.rotation.y = Math.PI;     // druga łopata po przeciwnej stronie
      rotor.add(item);
    }
    // PF i LB kręcą się w jedną stronę, PB i LF w drugą
    rotor.userData.dir = front === (my > 0) ? 1 : -1;
    rotors.push(rotor);
    group.add(rotor);

    // --- osłona: łuk torusa R21 / rurka ø2,5, z = 34, otwór 80° ku środkowi drona ---
    if (guards) {
      const material = front ? mats.accent : mats.prop;
      const outward = Math.atan2(sz(my), sx(mx));           // kierunek "na zewnątrz"
      const arc = new THREE.Mesh(
        new THREE.TorusGeometry(mm(GUARD_RADIUS_MM), mm(1.25), 8, 48,
          (360 - GUARD_GAP_DEG) * DEG),
        material);
      arc.position.set(sx(mx), sy(GUARD_Z_MM), sz(my));
      // X=90° kładzie pierścień płasko do poziomu; obrót w tej płaszczyźnie robi rotation.y.
      // Torus biegnie od kąta 0 do (360-gap), więc przerwa leży w [360-gap, 360],
      // czyli jej ŚRODEK wypada na kącie 360 - gap/2 (w układzie lokalnym).
      // Obrót: środek przerwy ma trafić w kierunek od silnika do środka drona.
      const towardCenter = outward + Math.PI;
      arc.rotation.order = 'XYZ';
      arc.rotation.set(Math.PI / 2, 0, towardCenter + (GUARD_GAP_DEG * DEG) / 2);
      statics.push(arc);

      // 2 szprychy: od (promień 4, z 20) do łuku (promień 21, z 34), ±55° od "na zewnątrz"
      for (const side of [-1, 1]) {
        const phi = outward + side * 55 * DEG;
        rod(1,
          [mx + Math.cos(phi) * 4, my + Math.sin(phi) * 4, 20],
          [mx + Math.cos(phi) * GUARD_RADIUS_MM, my + Math.sin(phi) * GUARD_RADIUS_MM,
            GUARD_Z_MM],
          material);
      }
    }
  }

  // siatki statyczne: bez scalania (scalanie zmienia normalne na wspólnych wierzchołkach)
  for (const item of statics) {
    item.castShadow = true;
    group.add(item);
  }
  const bodyMesh = statics.find((item) => item.material === mats.shell);
  if (bodyMesh) bodyMesh.name = 'body';

  return { group, rotors, size: measure(group) };
}

/**
 * Zaokrąglony prostopadłościan jako jedna spójna bryła (Minkowski'ego rdzenia i kuli
 * o promieniu r), próbkowany regularną siatką po każdej ze ścian, ze zszyciem
 * wzdłuż krawędzi. Normalne liczone analitycznie - gładkie, bez szwów.
 * Obrys bryły = len × height × width.
 */
function roundedBoxGeometry(len, height, width, r) {
  const half = [len / 2, height / 2, width / 2];
  const rr = Math.max(0.0002, Math.min(r, half[0] - 0.0002, half[1] - 0.0002,
    half[2] - 0.0002));
  const core = [half[0] - rr, half[1] - rr, half[2] - rr];   // półwymiary rdzenia
  const N = 24;                                              // podział ściany (kwadraty)
  const positions = [];
  const normals = [];

  // punkt powierzchni dla punktu q lezacego na scianie pudełka o polwymiarach 1:
  // rdzeń w kierunku "kanciastym" + odsunięcie o rr tylko na krawędziach i narożnikach
  const surfacePoint = (q) => {
    // kierunek od środka (do liczenia normalnej)
    const k = Math.max(Math.abs(q[0]), Math.abs(q[1]), Math.abs(q[2]));
    const dir = [q[0] / k, q[1] / k, q[2] / k];
    // punkt na PŁASKIEJ ścianie (bez zaokrąglenia) - składowe prostopadłe do osi ściany
    const flat = [dir[0] * half[0], dir[1] * half[1], dir[2] * half[2]];
    // rzut na zaokrągloną bryłę: współrzędne przycięte do core, potem odsunięcie o rr
    const clamped = [
      Math.max(-core[0], Math.min(core[0], flat[0])),
      Math.max(-core[1], Math.min(core[1], flat[1])),
      Math.max(-core[2], Math.min(core[2], flat[2])),
    ];
    const out = [flat[0] - clamped[0], flat[1] - clamped[1], flat[2] - clamped[2]];
    const ol = Math.hypot(out[0], out[1], out[2]);
    let n;
    let p;
    if (ol < 1e-9) {
      // punkt na płaskiej części ściany - normalna wzdłuż osi ściany (dominująca)
      const axis = Math.abs(dir[0]) >= Math.abs(dir[1]) && Math.abs(dir[0]) >= Math.abs(dir[2])
        ? 0 : (Math.abs(dir[1]) >= Math.abs(dir[2]) ? 1 : 2);
      n = [0, 0, 0];
      n[axis] = Math.sign(dir[axis]) || 1;
      p = [clamped[0] + n[0] * rr, clamped[1] + n[1] * rr, clamped[2] + n[2] * rr];
    } else {
      n = [out[0] / ol, out[1] / ol, out[2] / ol];
      p = [clamped[0] + n[0] * rr, clamped[1] + n[1] * rr, clamped[2] + n[2] * rr];
    }
    return { p, n };
  };

  // szesc scian: (os, znak, dwie osie plaszczyzny)
  const faces = [];
  for (let axis = 0; axis < 3; axis += 1) {
    const u = (axis + 1) % 3;
    const v = (axis + 2) % 3;
    for (const sign of [-1, 1]) faces.push({ axis, sign, u, v });
  }
  for (const face of faces) {
    for (let i = 0; i < N; i += 1) {
      for (let j = 0; j < N; j += 1) {
        const corners = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j], [i + 1, j + 1], [i, j + 1]];
        const pts = corners.map(([gi, gj]) => {
          const q = [0, 0, 0];
          q[face.axis] = face.sign;
          q[face.u] = (gi / N) * 2 - 1;
          q[face.v] = (gj / N) * 2 - 1;
          return surfacePoint(q);
        });
        for (const { p, n } of pts) {
          positions.push(p[0], p[1], p[2]);
          normals.push(n[0], n[1], n[2]);
        }
      }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  return geo;
}

/** Ustaw walec (domyślnie wzdłuż osi Y) zgodnie z kierunkiem `dir`. */
function orientAlong(mesh, dir) {
  const axis = new THREE.Vector3(dir.x, dir.y, dir.z).normalize();
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);
}

//: Rejestr modeli dronów (adaptery) - nowe modele dodaje się tutaj
export const DRONE_MODELS = { tello: createTello };

export function createDroneModel(type = 'tello', options = {}) {
  const factory = DRONE_MODELS[type] || createTello;
  return factory(options);
}

