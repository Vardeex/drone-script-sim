// Scena three.js: podłoże z siatką, osie, model drona, trasa i znaczniki.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { colorForHeight, clamp } from './util.js';
import { toScene } from './timeline.js';
import { createDroneModel } from './drone_model.js';

const M = 100; // 1 skala sceny = 100 cm (1 m)

export class DroneScene {
  constructor(container) {
    this.container = container;
    this.pickables = [];       // znaczniki komend (raycast)
    this.cameraMode = 'orbit';
    this.showTrail = true;

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.shadowMap.enabled = true;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0d1117);
    this.scene.fog = new THREE.Fog(0x0d1117, 18, 46);

    this.camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.05, 400);
    this.camera.position.set(3.2, 2.6, 3.8);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 0.9, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 0.4;
    this.controls.maxDistance = 60;

    this._buildLights();
    this._buildGround();
    this._buildAxes();
    this._buildDrone();
    this._buildOverlays();

    this.trailGroup = new THREE.Group();
    this.markerGroup = new THREE.Group();
    this.scene.add(this.trailGroup, this.markerGroup);

    this._spinner = 0;
    this._clock = new THREE.Clock();
    this._lastSample = null;

    window.addEventListener('resize', () => this.resize());
    new ResizeObserver(() => this.resize()).observe(container);
    this._animate();
  }


  // ------------------------------------------------------------- konstrukcja
  _buildLights() {
    this.scene.add(new THREE.HemisphereLight(0xbfd8ff, 0x0a0f16, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(6, 12, 5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -10;
    key.shadow.camera.right = 10;
    key.shadow.camera.top = 10;
    key.shadow.camera.bottom = -10;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x38bdf8, 0.5);
    rim.position.set(-8, 4, -6);
    this.scene.add(rim);
    this.keyLight = key;
  }

  _buildGround() {
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(120, 120),
      new THREE.MeshStandardMaterial({ color: 0x111a24, roughness: 1, metalness: 0 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);

    // siatka co 1 m (główna) i co 10 cm (drobna, subtelna)
    const grid = new THREE.GridHelper(40, 40, 0x3a4a5e, 0x223041);
    grid.material.opacity = 0.85;
    grid.material.transparent = true;
    this.scene.add(grid);

    const fine = new THREE.GridHelper(20, 200, 0x1b2634, 0x1b2634);
    fine.material.opacity = 0.5;
    fine.material.transparent = true;
    fine.position.y = 0.001;
    this.scene.add(fine);
    this._groundGrid = fine;
  }

  // Etykiety HTML (ostre, niezależne od rozdzielczości) rzutowane z kamery.
  addLabel(text, color, position, options = {}) {
    const node = document.createElement('div');
    node.className = `scene-label${options.small ? ' small' : ''}`;
    node.textContent = text;
    node.style.color = color;
    this.container.append(node);
    const label = { node, position: position.clone(), visible: options.visible !== false };
    this.labels.push(label);
    return label;
  }

  _updateLabels() {
    const rect = this.container.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const point = new THREE.Vector3();
    for (const label of this.labels) {
      point.copy(label.position).project(this.camera);
      const inFront = point.z < 1;
      const x = (point.x * 0.5 + 0.5) * rect.width;
      const y = (-point.y * 0.5 + 0.5) * rect.height;
      const onScreen = inFront && x > -80 && x < rect.width + 80 && y > -30 && y < rect.height + 30;
      label.node.style.display = label.visible && onScreen ? 'block' : 'none';
      label.node.style.left = `${x}px`;
      label.node.style.top = `${y}px`;
    }
  }

  _buildAxes() {
    this.labels = [];
    // układ osi: X (przód) czerwona, Y drona = -Z sceny (lewo) zielona, Z drona (góra) niebieska
    const axes = [
      { dir: [1, 0, 0], color: 0xef4444, label: 'X (przód)', len: 2.4 },
      { dir: [0, 0, -1], color: 0x22c55e, label: 'Y (lewo)', len: 2.4 },
      { dir: [0, 1, 0], color: 0x3b82f6, label: 'Z (góra)', len: 2.2 },
    ];
    for (const axis of axes) {
      const direction = new THREE.Vector3(...axis.dir).normalize();
      this.scene.add(new THREE.ArrowHelper(direction, new THREE.Vector3(0, 0.01, 0), axis.len,
        axis.color, 0.18, 0.09));
      this.addLabel(axis.label, `#${axis.color.toString(16).padStart(6, '0')}`,
        direction.clone().multiplyScalar(axis.len + 0.12), { small: true });
    }

    // punkt startu - pierścień + napis
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.16, 0.22, 40),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, side: THREE.DoubleSide,
        transparent: true, opacity: 0.9 }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.004;
    this.scene.add(ring);
    this.addLabel('START', '#7dd3fc', new THREE.Vector3(0, 0.03, 0.3), { small: true });
  }

  _buildDrone() {
    // Model drona pochodzi z osobnego modułu (adaptery: patrz drone_model.js).
    // Model ma dno w y=0 i środek obrotu w środku geometrycznym.
    this.droneGroup = new THREE.Group();   // przenosi pozycję/yaw (skala bez wpływu na yaw)
    this.droneScale = new THREE.Group();   // tylko skalowanie modelu (×1, ×3, ×5, ×10)
    this.droneGroup.add(this.droneScale);
    this.scene.add(this.droneGroup);
    this.droneOptions = { guards: true, accent: 0x2f86b3 };
    this.droneModelScale = 5;
    this._rebuildDroneModel();

    // etykieta kierunku przodu nad dronem (aktualizowana razem z pozycją/yaw)
    this.frontMarker = this.addLabel('przód', '#93c5fd', new THREE.Vector3(), { small: true });
  }

  /** (Prze)buduj model drona - wywoływane przy zmianie osłon/typu modelu. */
  _rebuildDroneModel() {
    const previous = this.droneScale.children.slice();
    for (const child of previous) {
      this.droneScale.remove(child);
      child.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) node.material.dispose();
      });
    }
    const model = createDroneModel('tello', this.droneOptions);
    this.drone = model.group;
    this.engines = model.rotors;
    this.droneSize = model.size;
    this.droneScale.add(this.drone);
    this.applyDroneScale(this.droneModelScale);
    this._updateShadowSize();
  }

  /** Skala modelu drona (tylko model - trasa i telemetria pozostają w prawdziwej skali). */
  applyDroneScale(factor) {
    this.droneModelScale = factor;
    this.droneScale.scale.setScalar(factor);
    const size = this.droneSize || new THREE.Vector3(0.1, 0.04, 0.09);
    const radius = Math.max(size.x, size.z) / 2;
    if (this.shadowDisc) this.shadowDisc.scale.setScalar(radius * factor * 0.85 / 0.12);
    if (this.shadowArrow) this.shadowArrow.scale.setScalar(0.55 + factor * 0.05);
    if (this.frontMarker) this.frontMarker.offset = 0.3 + radius * factor * 1.1;
  }

  /** Ułóż geometrię cienia/kółka pod dronem w zależności od rozmiaru modelu. */
  _updateShadowSize() {
    const size = this.droneSize || new THREE.Vector3(0.1, 0.04, 0.09);
    const radius = Math.max(size.x, size.z) / 2;
    if (this.shadowDisc) this.shadowDisc.scale.setScalar(radius * this.droneModelScale * 0.85 / 0.12);
  }

  _buildOverlays() {
    // pionowa kreska od drona do ziemi (wysokość)
    this.heightLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)]),
      new THREE.LineDashedMaterial({ color: 0x38bdf8, dashSize: 0.06, gapSize: 0.05,
        transparent: true, opacity: 0.75 }),
    );
    this.heightLine.computeLineDistances();
    this.scene.add(this.heightLine);

    // cień/kółko pod dronem (rzutowane na podłoże - pozycja i wysokość)
    this.shadowDisc = new THREE.Mesh(new THREE.CircleGeometry(0.12, 32),
      new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.38,
        depthWrite: false }));
    this.shadowDisc.rotation.x = -Math.PI / 2;
    this.shadowDisc.position.y = 0.002;
    this.scene.add(this.shadowDisc);

    // opcjonalna mała strzałka kierunku przodu na cieniu (przełącznik w UI)
    this.shadowArrow = new THREE.Group();
    const arrowMat = new THREE.MeshBasicMaterial({ color: 0x93c5fd, transparent: true,
      opacity: 0.85, depthWrite: false });
    const shaft = new THREE.Mesh(new THREE.PlaneGeometry(0.16, 0.018), arrowMat);
    shaft.rotation.x = -Math.PI / 2;
    shaft.position.x = 0.09;
    const head = new THREE.Mesh(new THREE.CircleGeometry(0.028, 3), arrowMat);
    head.rotation.x = -Math.PI / 2;
    head.rotation.z = -Math.PI / 2;
    head.position.x = 0.19;
    this.shadowArrow.add(shaft, head);
    this.shadowArrow.position.y = 0.004;
    this.shadowArrow.visible = false;
    this.scene.add(this.shadowArrow);
    this.showShadowArrow = false;

    // wektor prędkości
    this.velocityArrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(), 0.3, 0xfacc15, 0.08, 0.04);
    this.velocityArrow.visible = false;
    this.scene.add(this.velocityArrow);
  }


  // ------------------------------------------------------------------- trasa
  /** Ustaw dane trasy: próbki telemetrii i komendy (zdarzenia). */
  setFlight(samples, events, maxHeight) {
    this.samples = samples || [];
    this.events = events || [];
    // skala kolorów w cm, co najmniej 1 m - inaczej lot na 80 cm daje jednolity kolor
    this.maxHeight = Math.max(maxHeight || 0, 100);
    this._buildTrail();
    this._buildMarkers();
  }

  _disposeGroup(group) {
    for (const child of [...group.children]) {
      group.remove(child);
      if (child.traverse) {
        child.traverse((node) => {
          if (node.geometry) node.geometry.dispose();
          if (node.material) {
            if (node.material.map) node.material.map.dispose();
            node.material.dispose();
          }
        });
      }
    }
  }

  _buildTrail() {
    this._disposeGroup(this.trailGroup);
    const samples = this.samples;
    if (samples.length < 2) return;
    const positions = [];
    const colors = [];
    for (const s of samples) {
      const p = toScene(s);
      positions.push(p.x / M, p.y / M + 0.02, p.z / M);
      const c = colorForHeight(s.z, this.maxHeight);
      colors.push(c[0] / 255, c[1] / 255, c[2] / 255);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    this.trailGroup.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ vertexColors: true })));

    // "cień" trasy na podłożu
    const groundPositions = [];
    for (const s of samples) {
      const p = toScene(s);
      groundPositions.push(p.x / M, 0.006, p.z / M);
    }
    const gGeo = new THREE.BufferGeometry();
    gGeo.setAttribute('position', new THREE.Float32BufferAttribute(groundPositions, 3));
    this.trailGroup.add(new THREE.Line(gGeo, new THREE.LineBasicMaterial({
      color: 0x2c3b4d, transparent: true, opacity: 0.9,
    })));
  }

  _buildMarkers() {
    this._disposeGroup(this.markerGroup);
    this.pickables = [];
    for (const event of this.events) {
      const p = toScene(event);
      const color = event.status === 'error' ? 0xef4444
        : event.status === 'warning' ? 0xf59e0b : 0x38bdf8;
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(0.024, 10, 10),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35 }),
      );
      marker.position.set(p.x / M, p.y / M + 0.03, p.z / M);
      marker.userData.event = event;
      marker.userData.kind = 'marker';
      this.markerGroup.add(marker);
      this.pickables.push(marker);

      // pionowa linia do ziemi pokazuje wysokość
      if (p.y > 0.5) {
        const geo = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(p.x / M, 0.01, p.z / M),
          new THREE.Vector3(p.x / M, p.y / M, p.z / M),
        ]);
        const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
          color, dashSize: 0.05, gapSize: 0.04, transparent: true, opacity: 0.45,
        }));
        line.computeLineDistances();
        this.markerGroup.add(line);
      }

      // numer komendy wprost na znaczniku (bez osobnej "plakietki" zasłaniającej dron)
      const label = this._numberLabel(event.index, color);
      label.position.set(p.x / M, p.y / M + 0.03, p.z / M);
      label.userData.event = event;
      label.userData.kind = 'label';
      label.scale.set(0.1, 0.0417, 1);
      this.markerGroup.add(label);
      this.pickables.push(label);
    }
  }

  _numberLabel(index, color) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 68;
    const ctx = canvas.getContext('2d');
    ctx.beginPath();
    ctx.arc(64, 34, 30, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(10,14,20,0.92)';
    ctx.fill();
    ctx.lineWidth = 5;
    ctx.strokeStyle = `#${color.toString(16).padStart(6, '0')}`;
    ctx.stroke();
    ctx.fillStyle = '#e8f0fa';
    const text = String(index);
    ctx.font = `700 ${text.length > 2 ? 26 : 32}px "Segoe UI", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 35);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: texture, transparent: true, depthTest: false, depthWrite: false,
    }));
    sprite.scale.set(0.12, 0.0637, 1);
    sprite.renderOrder = 100;
    return sprite;
  }

  // --------------------------------------------------------------- aktualizacja
  update(sample) {
    if (!sample) return;
    this._lastSample = sample;
    const p = toScene(sample);
    const position = new THREE.Vector3(p.x / M, Math.max(p.y, 0) / M, p.z / M);
    this.droneGroup.position.copy(position);
    // yaw drona: 0 = przód w +X, dodatni = obrót w lewo (CCW wokół pionu)
    this.droneGroup.rotation.y = THREE.MathUtils.degToRad(sample.yaw);
    if (this.frontMarker) {
      const yawRad = THREE.MathUtils.degToRad(sample.yaw);
      const offset = this.frontMarker.offset || 0.3;
      this.frontMarker.position.set(
        position.x + Math.cos(yawRad) * offset,
        position.y + 0.12,
        position.z - Math.sin(yawRad) * offset,
      );
    }

    const flying = sample.state === 'airborne' || sample.z > 1;

    // linia wysokości
    const linePos = this.heightLine.geometry.attributes.position;
    linePos.setXYZ(0, position.x, 0.005, position.z);
    linePos.setXYZ(1, position.x, position.y, position.z);
    linePos.needsUpdate = true;
    this.heightLine.computeLineDistances();
    this.heightLine.visible = position.y > 0.02;

    const faint = clamp(1 - position.y / 3, 0.2, 1);
    this.shadowDisc.position.set(position.x, 0.002, position.z);
    this.shadowDisc.material.opacity = 0.38 * faint;
    const yawRad = THREE.MathUtils.degToRad(sample.yaw);
    this.shadowArrow.position.set(position.x, 0.004, position.z);
    this.shadowArrow.rotation.y = yawRad;
    this.shadowArrow.visible = this.showShadowArrow;
    if (this.showShadowArrow) this.shadowArrow.children.forEach((c) => {
      c.material.opacity = 0.85 * faint;
    });

    // wektor prędkości (w układzie sceny)
    const v = [sample.vx, sample.vz, -sample.vy];
    const speed = Math.hypot(v[0], v[1], v[2]);
    if (speed > 1) {
      this.velocityArrow.visible = true;
      const dir = new THREE.Vector3(v[0], v[1], v[2]).normalize();
      this.velocityArrow.position.copy(position);
      this.velocityArrow.setDirection(dir);
      this.velocityArrow.setLength(Math.min(speed / 100, 1.2), 0.08, 0.04);
    } else {
      this.velocityArrow.visible = false;
    }

    this._flying = flying;
  }

  /** Docelowa odległość kamery śledzącej zależna od skali modelu (×1 → ~1,2 m, ×10 → ~5 m). */
  _followDistance() {
    return 0.95 + 0.38 * Math.max(1, this.droneModelScale);
  }

  /** Ustaw skalę modelu drona (×1, ×3, ×5, ×10) - trasa i telemetria bez zmian. */
  setDroneSize(factor) {
    this.applyDroneScale(Number(factor) || 1);
    if (this.cameraMode === 'follow') this.setCameraMode('follow');
  }

  /** Włącz/wyłącz osłony śmigieł w modelu. */
  setGuards(enabled) {
    this.droneOptions = { ...this.droneOptions, guards: Boolean(enabled) };
    this._rebuildDroneModel();
  }

  /** Mała strzałka kierunku przodu na cieniu drona. */
  setShadowArrow(enabled) {
    this.showShadowArrow = Boolean(enabled);
    this.shadowArrow.visible = this.showShadowArrow;
  }

  /** Szybkość odtwarzania - przy 8x gęstość siatki/_labels mniejsza (płynność). */
  setPlaybackRate(rate) {
    const fast = rate >= 4;
    this._lowDetail = fast;
    if (this._groundGrid) this._groundGrid.visible = !fast;
    if (this.velocityArrow) this.velocityArrow.visible = this.velocityArrow.visible && !fast;
  }

  /** Ustaw tryb kamery śledzącej z odległością dopasowaną do skali modelu. */
  setCameraMode(mode) {
    this.cameraMode = mode;
    if (mode === 'top') {
      const target = this.controls.target;
      const yaw = this._lastSample ? THREE.MathUtils.degToRad(this._lastSample.yaw) : 0;
      this.camera.up.set(Math.cos(yaw), 0, Math.sin(yaw));
      this.camera.position.set(target.x, 8, target.z);
      this.camera.lookAt(target);
    } else {
      this.camera.up.set(0, 1, 0);
      if (mode === 'follow') {
        // dopasuj odległość kamery do rozmiaru modelu (×1..×10)
        const reach = this._followDistance();
        const offset = this.camera.position.clone().sub(this.controls.target);
        const desired = new THREE.Vector3(reach * 0.55, reach * 0.42, reach * 0.55);
        if (offset.length() < reach * 0.45 || offset.length() > reach * 1.6
            || Math.abs(offset.length() - reach) > reach * 0.7) {
          this.camera.position.copy(this.controls.target).add(desired);
        }
      }
    }
  }

  fitView() {
    const samples = this.samples || [];
    const box = new THREE.Box3();
    for (const s of samples) {
      const p = toScene(s);
      box.expandByPoint(new THREE.Vector3(p.x / M, p.y / M, p.z / M));
    }
    if (box.isEmpty()) box.expandByPoint(new THREE.Vector3(0, 0.8, 0));
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() / 2, 0.8);
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const distance = (radius / Math.sin(fov / 2)) * 0.95;
    this.controls.target.copy(center);
    this.camera.up.set(0, 1, 0);
    this.camera.position.set(center.x + distance * 0.62, center.y + distance * 0.55,
      center.z + distance * 0.62);
    if (this.cameraMode === 'top') {
      this.setCameraMode('top');
    }
    this.controls.update();
  }

  resize() {
    const { clientWidth: width, clientHeight: height } = this.container;
    if (!width || !height) return;
    this.renderer.setSize(width, height);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  // ------------------------------------------------------------------ raycast
  pick(clientX, clientY) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, this.camera);
    const hits = raycaster.intersectObjects(this.pickables, false);
    return hits.length ? hits[0].object.userData.event : null;
  }

  _animate = () => {
    requestAnimationFrame(this._animate);
    const dt = this._clock.getDelta();
    // wirniki: szybki obrót w locie, zatrzymane na ziemi
    const spin = this._flying ? 28 * dt : 0;
    this._spinner += spin;
    if (this.engines) {
      for (const rotor of this.engines) {
        rotor.rotation.y += spin * rotor.userData.dir;
      }
    }
    if (this.cameraMode === 'follow' && this._lastSample) {
      const p = toScene(this._lastSample);
      // odległość kamery śledzącej rośnie z rozmiarem modelu (×1 → ~1,3 m, ×10 → ~4,7 m)
      const reach = this._followDistance();
      const target = new THREE.Vector3(p.x / M, p.y / M + 0.05, p.z / M);
      const offset = this.camera.position.clone().sub(this.controls.target);
      if (offset.length() > reach * 1.6) offset.setLength(reach * 1.6);
      this.controls.target.lerp(target, clamp(dt * 6, 0, 1));
      this.camera.position.copy(this.controls.target).add(offset);
    } else if (this.cameraMode === 'top' && this._lastSample) {
      const p = toScene(this._lastSample);
      const target = new THREE.Vector3(p.x / M, 0, p.z / M);
      const previous = this.controls.target.clone();
      this.controls.target.lerp(target, clamp(dt * 4, 0, 1));
      const shift = this.controls.target.clone().sub(previous);
      this.camera.position.add(shift);
      const yaw = THREE.MathUtils.degToRad(this._lastSample.yaw);
      this.camera.up.set(Math.cos(yaw), 0, Math.sin(yaw));
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    if (this.labels) this._updateLabels();
  };
}

export { M };
