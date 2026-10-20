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

//: Założenia modelu (proporcje ze zdjęć; śmigła nie kolidują z sąsiednimi)
//: Warunki: 2*motorX - propDiameter > 0, 2*motorZ - propDiameter > 0,
//: motorX + propDiameter/2 <= 49 mm, motorZ + promień osłony <= 46,25 mm.
export const TELLO_GEOMETRY_MM = {
  propDiameter: 40.0,     // mniejsze niż rozstaw silników -> śmigła się nie przecinają
  motorX: 26.0,           // oś silnika: |x|  (rozstaw wzdłuż przodu 52 mm)
  motorZ: 23.0,           // oś silnika: |z|  (rozstaw na boki 46 mm)
  bodyLength: 66.0,
  bodyWidth: 46.0,
  bodyHeight: 20.0,
  legsHeight: 6.0,        // nóżki: dno korpusu nad podłożem (dno drona w y=0)
  guardThickness: 2.0,    // grubość pałąka osłony
  guardExtra: 1.9,        // promień osłony = promień śmigła + zapas
  guardY: 40.9,           // wysokość płaszczyzny osłon (góra = 41,9 mm)
  motorHeight: 12.0,
  propY: 36.5,
};

const mm = (value) => value / 1000;

function materials(accentHex) {
  return {
    shell: new THREE.MeshStandardMaterial({
      color: 0x555d66, roughness: 0.55, metalness: 0.35, flatShading: true,
    }),
    dark: new THREE.MeshStandardMaterial({
      color: 0x30353b, roughness: 0.7, metalness: 0.2, flatShading: true,
    }),
    prop: new THREE.MeshStandardMaterial({
      color: 0x25292e, roughness: 0.5, metalness: 0.1, flatShading: true,
    }),
    accent: new THREE.MeshStandardMaterial({
      color: accentHex, roughness: 0.5, metalness: 0.3,
      emissive: accentHex, emissiveIntensity: 0.04,
    }),
    lens: new THREE.MeshStandardMaterial({
      color: 0x0b0e12, roughness: 0.12, metalness: 0.95,
    }),
  };
}

/** Bounding box modelu (w jednostkach sceny). */
export function measure(group) {
  const box = new THREE.Box3().setFromObject(group);
  return box.getSize(new THREE.Vector3());
}

/**
 * Zbuduj model drona Tello.
 *
 * @param {object} [options]
 * @param {boolean} [options.guards=true] - osłony śmigieł (pałąki)
 * @param {number} [options.accent=0x38bdf8] - kolor akcentu przednich osłon
 * @returns {{group: THREE.Group, rotors: THREE.Object3D[], size: THREE.Vector3}}
 */
export function createTello({ guards = true, accent = 0x2f86b3 } = {}) {
  const g = TELLO_GEOMETRY_MM;
  const mats = materials(accent);
  const group = new THREE.Group();
  group.name = 'tello';
  const staticMeshes = [];
  const add = (geometry, material, x, y, z, rot = null) => {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    if (rot) mesh.rotation.set(rot[0], rot[1], rot[2]);
    staticMeshes.push(mesh);
    return mesh;
  };

  const bodyLen = mm(g.bodyLength);
  const bodyWid = mm(g.bodyWidth);
  const bodyH = mm(g.bodyHeight);
  const bodyBottom = mm(g.legsHeight);
  const midY = bodyBottom + bodyH / 2;

  // nóżki: podpora, aby dno drona leżało na podłożu (y = 0)
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      add(new THREE.BoxGeometry(mm(6), mm(g.legsHeight), mm(6)), mats.dark,
        sx * mm(g.bodyLength) * 0.28, mm(g.legsHeight) / 2, sz * mm(g.bodyWidth) * 0.30);
    }
  }

  // korpus: płaski, zaokrąglony prostopadłościan + węższy "grzbiet" baterii
  add(new THREE.BoxGeometry(bodyLen, bodyH, bodyWid), mats.shell, 0, midY, 0);
  add(new THREE.BoxGeometry(bodyLen * 0.70, mm(5.0), bodyWid * 0.62), mats.shell,
    0, bodyBottom + bodyH + mm(1.5), 0);
  // grill z przodu (ciemny) i kamera wpuszczona w korpus (przód, tuż pod górną krawędzią)
  const camY = bodyBottom + bodyH * 0.66;
  add(new THREE.BoxGeometry(mm(1.4), bodyH * 0.5, bodyWid * 0.55), mats.dark,
    bodyLen / 2 - mm(0.3), midY, 0);
  add(new THREE.BoxGeometry(mm(2.4), mm(7.0), mm(10.0)), mats.dark,
    bodyLen / 2 - mm(0.8), camY, 0);
  add(new THREE.CylinderGeometry(mm(2.9), mm(2.9), mm(1.4), 14), mats.lens,
    bodyLen / 2, camY, 0, [0, 0, Math.PI / 2]);

  // ramiona, silniki, śmigła (pary po przekątnej kręcą się przeciwnie)
  const dx = mm(g.motorX);
  const dz = mm(g.motorZ);
  const motorTop = bodyBottom + bodyH + mm(g.motorHeight);
  const motorMid = motorTop - mm(g.motorHeight) / 2;
  const propY = mm(g.propY);
  const corners = [[1, -1], [1, 1], [-1, 1], [-1, -1]]; // PF, PB, LB, LF
  const rotors = [];
  for (const [sx, sz] of corners) {
    const front = sx > 0;
    const mx = sx * dx;
    const mz = sz * dz;
    const heading = Math.atan2(-mz, mx);
    // ramię od korpusu do silnika (pod korpusem, nie wystaje poza obrys)
    const armLen = Math.hypot(mx, mz) - mm(18);
    add(new THREE.BoxGeometry(armLen, mm(5.0), mm(7.0)), mats.shell,
      mx * 0.46, bodyBottom + bodyH * 0.42, mz * 0.46, [0, heading, 0]);
    // silnik
    add(new THREE.CylinderGeometry(mm(5.0), mm(5.8), mm(g.motorHeight), 14), mats.dark,
      mx, motorMid, mz);
    // kołnierz silnika
    add(new THREE.CylinderGeometry(mm(6.6), mm(6.6), mm(1.6), 14), mats.shell,
      mx, motorMid + mm(g.motorHeight) / 2 - mm(1.2), mz);

    // śmigło (2 łopaty) - obraca się wokół osi Y
    const rotor = new THREE.Group();
    rotor.position.set(mx, propY, mz);
    const half = mm(g.propDiameter) / 2;
    for (let k = 0; k < 2; k += 1) {
      const sign = k === 0 ? 1 : -1;
      const blade = new THREE.Mesh(
        new THREE.BoxGeometry(half * 0.96, mm(1.0), mm(5.2)),
        front && sign > 0 ? mats.accent : mats.prop,
      );
      blade.position.set(half * 0.48 * sign, 0, 0);
      blade.rotation.z = sign * 0.1;
      rotor.add(blade);
    }
    rotor.add(new THREE.Mesh(new THREE.CylinderGeometry(mm(2.2), mm(2.2), mm(3), 10), mats.dark));
    rotor.userData.dir = sx * sz > 0 ? 1 : -1;
    group.add(rotor);
    rotors.push(rotor);
  }

  // osłony śmigieł: pierścienie nad śmigłami + pionowe wsporniki do silnika
  if (guards) {
    const guardR = mm(g.propDiameter) / 2 + mm(g.guardExtra);
    const tube = mm(g.guardThickness) / 2;
    const guardY = mm(g.guardY);
    for (const [sx, sz] of corners) {
      // osłona: ciemne ramię w ŁUKU (jak w Tello) - łuk w płaszczyźnie pionowej
      // nad śmigłem, biegnący od silnika w stronę zewnętrznego narożnika
      const mx = sx * dx;
      const mz = sz * dz;
      const front = sx > 0;
      const mat = front ? mats.accent : mats.dark;
      // łuk biegnie w płaszczyźnie pionowej od pierścienia do osi silnika
      const arc = new THREE.Mesh(
        new THREE.TorusGeometry(guardR, tube, 5, 14, Math.PI), mat);
      arc.position.set(mx, guardY, mz);
      arc.rotation.set(Math.PI / 2, 0, Math.PI + Math.atan2(-mz, mx));
      staticMeshes.push(arc);
      // pozioma obejma wokół śmigła
      const ring = new THREE.Mesh(new THREE.TorusGeometry(guardR, tube * 0.7, 4, 20), mat);
      ring.position.set(mx, guardY, mz);
      ring.rotation.x = Math.PI / 2;
      staticMeshes.push(ring);
      for (const side of [-1, 1]) {
        const post = new THREE.Mesh(
          new THREE.BoxGeometry(mm(1.6), guardY - motorTop, mm(1.6)), mats.dark);
        post.position.set(mx + side * guardR * 0.8, (guardY + motorTop) / 2, mz);
        staticMeshes.push(post);
      }
    }
  }

  // scalenie statycznych siatek per materiał (mniej draw calls)
  for (const mesh of mergeByMaterial(staticMeshes)) {
    mesh.castShadow = true;
    group.add(mesh);
  }

  // środek obrotu = środek geometryczny; dno drona w y = 0
  return { group, rotors, size: measure(group) };
}

/** Scal siatki o tym samym materiale (mniej draw calls przy odtwarzaniu). */
function mergeByMaterial(meshes) {
  const buckets = new Map();
  for (const mesh of meshes) {
    mesh.updateMatrix();
    if (!buckets.has(mesh.material)) buckets.set(mesh.material, []);
    buckets.get(mesh.material).push(mesh);
  }
  const result = [];
  for (const [material, list] of buckets) {
    const merged = mergeGeometries(list.map((m) => {
      const geo = (m.geometry.index ? m.geometry.toNonIndexed() : m.geometry.clone());
      geo.applyMatrix4(m.matrix);
      return geo;
    }));
    if (merged) result.push(new THREE.Mesh(merged, material));
    else result.push(...list);
  }
  return result;
}

/** Scal geometrie (pozycje + normalne) - bez dodatków z three/examples. */
function mergeGeometries(geometries) {
  let total = 0;
  for (const geo of geometries) total += geo.attributes.position.count;
  const positions = new Float32Array(total * 3);
  const normals = new Float32Array(total * 3);
  let offset = 0;
  for (const geo of geometries) {
    positions.set(geo.attributes.position.array, offset * 3);
    if (geo.attributes.normal) normals.set(geo.attributes.normal.array, offset * 3);
    offset += geo.attributes.position.count;
    geo.dispose();
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  merged.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  merged.computeBoundingSphere();
  return merged;
}

//: Rejestr modeli dronów (adaptery) - nowe modele dodaje się tutaj
export const DRONE_MODELS = { tello: createTello };

export function createDroneModel(type = 'tello', options = {}) {
  const factory = DRONE_MODELS[type] || createTello;
  return factory(options);
}

