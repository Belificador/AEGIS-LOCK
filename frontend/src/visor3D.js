import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { addCameraMarkers } from "./components/viewport/camera-markers.js";
import { getVoltageReading, VOLTAGE_NORMAL_MAX_V, VOLTAGE_NORMAL_MIN_V } from "./voltage-reading.js";
import NAV_GRID from "../../models_3d/nav/navgrid.json";

const MODEL_URL = new URL("../../models_3d/oficina/edificio.glb", import.meta.url).href;
const MODEL_DISPLAY_SIZE = 16.5;
const MODEL_VIEW_FILL = 0.5;
const MODEL_VIEW_DIRECTION = new THREE.Vector3(1, 0.55, 1).normalize();
const ZONE_LIGHT_MAX_INTENSITY = 24;

export class Visor3D {
  constructor(container, { onLoad = () => {}, onError = () => {}, onCameraSelected = () => {} } = {}) {
    this.container = container;
    this.onLoad = onLoad;
    this.onError = onError;
    this.onCameraSelected = onCameraSelected;
    this.destroyed = false;
    this.zoneEvents = new Map();
    this.telemetryLights = new Map();
    this.cameraMarkers = null;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.pointerDown = null;
    this.model = null;
    this.animationFrame = null;
    this.resizeObserver = null;
    this.renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.domElement.className = "visor3d-canvas";
    this.renderer.domElement.setAttribute("aria-label", "Modelo tridimensional de la oficina");
    container.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 1000);
    this.camera.position.set(18, 12, 18);
    this.scene.add(new THREE.HemisphereLight(0xb9eaff, 0x172334, 2.1));
    const keyLight = new THREE.DirectionalLight(0xffffff, 3.2);
    keyLight.position.set(12, 18, 10);
    this.scene.add(keyLight);
    this.zoneLight = new THREE.PointLight(0x29cafa, 18, 100);
    this.zoneLight.position.set(-12, 8, -8);
    this.scene.add(this.zoneLight);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 80;
    this.hasUserOrbit = false;
    this.controls.addEventListener("start", () => { this.hasUserOrbit = true; });
    this._onPointerDown = (event) => {
      if (event.button !== 0) return;
      this.pointerDown = { id: event.pointerId, x: event.clientX, y: event.clientY };
    };
    this._onPointerUp = (event) => {
      const start = this.pointerDown;
      this.pointerDown = null;
      if (!start || start.id !== event.pointerId || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
      const marker = this._cameraMarkerAt(event.clientX, event.clientY);
      if (marker) this.cameraMarkers?.select(marker);
    };
    this._onPointerMove = (event) => {
      if (this.pointerDown) return;
      this.renderer.domElement.style.cursor = this._cameraMarkerAt(event.clientX, event.clientY) ? "pointer" : "grab";
    };
    this._onPointerCancel = () => { this.pointerDown = null; };
    this.renderer.domElement.addEventListener("pointerdown", this._onPointerDown);
    this.renderer.domElement.addEventListener("pointerup", this._onPointerUp);
    this.renderer.domElement.addEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.addEventListener("pointercancel", this._onPointerCancel);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.load();
    this.render();
  }

  load() {
    new GLTFLoader().load(MODEL_URL, ({ scene }) => {
      if (this.destroyed) {
        scene.traverse((node) => {
          if (!node.isMesh) return;
          node.geometry.dispose();
          for (const material of Array.isArray(node.material) ? node.material : [node.material]) material.dispose();
        });
        return;
      }
      this.model = scene;
      this.model.traverse((node) => {
        if (!node.isMesh) return;
        node.castShadow = true;
        node.receiveShadow = true;
        const clonedMaterials = (Array.isArray(node.material) ? node.material : [node.material]).map((sourceMaterial) => {
          const material = sourceMaterial.clone();
          return {
            material,
            color: material.color?.clone(),
            emissive: material.emissive?.clone(),
            emissiveIntensity: material.emissiveIntensity,
          };
        });
        node.material = Array.isArray(node.material) ? clonedMaterials.map(({ material }) => material) : clonedMaterials[0].material;
        node.userData.zoneBaseMaterials = clonedMaterials;
      });

      const bounds = new THREE.Box3().setFromObject(this.model);
      const size = bounds.getSize(new THREE.Vector3());
      const maxDimension = Math.max(size.x, size.y, size.z) || 1;
      this.model.scale.setScalar(MODEL_DISPLAY_SIZE / maxDimension);
      this.model.updateMatrixWorld(true);
      const scaledCenter = new THREE.Box3().setFromObject(this.model).getCenter(new THREE.Vector3());
      this.model.position.sub(scaledCenter);
      this.model.updateMatrixWorld(true);
      this.scene.add(this.model);
      this.createTelemetryLights();
      this.cameraMarkers = addCameraMarkers(THREE, this.model, MODEL_DISPLAY_SIZE / maxDimension, (camera) => {
        this.onCameraSelected(camera);
      });
      this.applyZoneEvents();
      this.resize();
      this.onLoad();
    }, undefined, (error) => {
      console.error("No se pudo cargar el modelo 3D de la oficina", error);
      if (!this.destroyed) this.onError(error);
    });
  }

  update(event) {
    const zone = event?.zona || event?.zone || "global";
    if (!this.model) {
      this.zoneEvents.set(normalize(zone), event);
      return;
    }
    this.zoneEvents.set(normalize(zone), event);
    this.applyZoneEvent(normalize(zone), event);
  }

  setIntrusionAlert(zone) {
    this.update({ tipo_evento: "acceso_pin", valor: "DENIED", zona: zone || "global" });
  }

  applyZoneEvents() {
    for (const [zone, event] of this.zoneEvents) this.applyZoneEvent(zone, event);
  }

  applyZoneEvent(zone, event) {
    const type = String(event.tipo_evento || event.event_type || "").toLowerCase();
    if (["iluminacion", "illumination", "lighting"].includes(type)) {
      this.applyTelemetryLighting(event);
      return;
    }

    const matching = [];
    this.model?.traverse((node) => {
      if (!node.isMesh || !isInZone(node, zone, event.metadata)) return;
      matching.push(node);
    });
    const severity = getEventColor(event);
    this.zoneLight.color.copy(severity.color);
    this.zoneLight.intensity = severity.intensity > 2 ? 34 : 18;
    for (const mesh of matching) {
      for (const base of mesh.userData.zoneBaseMaterials || []) {
        if (base.material.emissive) {
          base.material.emissive.copy(severity.color);
          base.material.emissiveIntensity = severity.intensity;
        } else if (base.material.color) {
          base.material.color.copy(base.color).lerp(severity.color, 0.22);
        }
      }
    }
  }

  createTelemetryLights() {
    const transform = NAV_GRID.transform || {};
    const scale = Number(transform.scale) || 1;
    const positionX = Number(transform.positionX) || 0;
    const positionY = Number(transform.positionY) || 0;
    const positionZ = Number(transform.positionZ) || 0;
    for (const zone of NAV_GRID.zones || []) {
      if (!Array.isArray(zone.centre) || zone.centre.length < 2) continue;
      const local = new THREE.Vector3(
        (zone.centre[0] - positionX) / scale,
        (2.25 - positionY) / scale,
        (zone.centre[1] - positionZ) / scale,
      );
      const light = new THREE.PointLight(0xffe9c7, 0, 14, 1.7);
      light.position.copy(this.model.localToWorld(local));
      light.userData.zoneId = zone.id;
      this.scene.add(light);
      this.telemetryLights.set(zone.id, light);
    }
  }

  applyTelemetryLighting(event) {
    const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
    const rawValue = event.illumination_percent ?? event.valor;
    const value = Number(rawValue ?? (metadata.factor_electrico != null ? Number(metadata.factor_electrico) * 100 : NaN));
    if (!Number.isFinite(value)) return;
    const level = THREE.MathUtils.clamp(value, 0, 100) / 100;
    const rawZoneId = metadata.zona_id;
    const zoneId = rawZoneId == null ? null : Number(rawZoneId);
    const targetLights = zoneId == null
      ? [...this.telemetryLights.values()]
      : [this.telemetryLights.get(zoneId)].filter(Boolean);
    for (const light of targetLights) light.intensity = ZONE_LIGHT_MAX_INTENSITY * level;
  }

  _cameraMarkerAt(clientX, clientY) {
    if (!this.cameraMarkers?.targets.length) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    this.pointer.set(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster.intersectObjects(this.cameraMarkers.targets, false)[0]?.object ?? null;
  }

  resize() {
    if (!this.container || !this.renderer) return;
    const { width, height } = this.container.getBoundingClientRect();
    if (width <= 0 || height <= 0) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    if (this.model && !this.hasUserOrbit) this.frameModel();
  }

  frameModel() {
    const bounds = new THREE.Box3().setFromObject(this.model);
    if (bounds.isEmpty()) return;
    const target = bounds.getCenter(new THREE.Vector3());
    const direction = MODEL_VIEW_DIRECTION.clone();
    const worldUp = new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(worldUp, direction).normalize();
    const viewUp = new THREE.Vector3().crossVectors(direction, right).normalize();
    const tanHalfVertical = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const tanHalfHorizontal = tanHalfVertical * this.camera.aspect;
    const corners = [
      new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.min.z),
      new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.max.z),
      new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.min.z),
      new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.max.z),
      new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.min.z),
      new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.max.z),
      new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.min.z),
      new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.max.z),
    ];
    let distance = 0;
    for (const corner of corners) {
      const offset = corner.sub(target);
      const depth = offset.dot(direction);
      const horizontalDistance = depth + Math.abs(offset.dot(right)) / (tanHalfHorizontal * MODEL_VIEW_FILL);
      const verticalDistance = depth + Math.abs(offset.dot(viewUp)) / (tanHalfVertical * MODEL_VIEW_FILL);
      distance = Math.max(distance, horizontalDistance, verticalDistance);
    }

    this.controls.target.copy(target);
    this.camera.position.copy(target).addScaledVector(direction, distance * 1.04);
    this.controls.update();
  }

  render() {
    if (this.destroyed || !this.renderer) return;
    this.animationFrame = window.requestAnimationFrame(() => this.render());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  destroy() {
    this.destroyed = true;
    window.cancelAnimationFrame(this.animationFrame);
    this.resizeObserver?.disconnect();
    this.renderer.domElement.removeEventListener("pointerdown", this._onPointerDown);
    this.renderer.domElement.removeEventListener("pointerup", this._onPointerUp);
    this.renderer.domElement.removeEventListener("pointermove", this._onPointerMove);
    this.renderer.domElement.removeEventListener("pointercancel", this._onPointerCancel);
    this.controls.dispose();
    this.cameraMarkers?.dispose();
    for (const light of this.telemetryLights.values()) this.scene.remove(light);
    this.telemetryLights.clear();
    this.model?.traverse((node) => {
      if (!node.isMesh) return;
      node.geometry.dispose();
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) material.dispose();
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
    this.model = null;
  }
}

function normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function isInZone(mesh, zone, metadata = {}) {
  const targets = [
    metadata.node,
    metadata.node_name,
    metadata.nodo,
    metadata.nodo_3d,
    metadata.mesh,
    metadata.mesh_name,
    metadata.room,
    metadata.habitacion,
    ...(Array.isArray(metadata.nodes) ? metadata.nodes : []),
  ].map(normalize).filter(Boolean);
  let node = mesh;
  while (node) {
    const name = normalize(node.name);
    if (name && (name.includes(zone) || zone.includes(name) || targets.some((target) => name.includes(target) || target.includes(name)))) return true;
    node = node.parent;
  }
  return false;
}

function getEventColor(event) {
  const type = String(event.tipo_evento || "").toLowerCase();
  const denied = type === "acceso_pin" && String(event.valor).toUpperCase() === "DENIED";
  const criticalTemperature = (type === "temperatura" || event.temperature_c != null) && Number(event.temperature_c ?? event.valor) > 38;
  const voltage = getVoltageReading(event);
  const powerFailure = voltage === 0;
  const voltageFluctuation = Array.isArray(event.alerts)
    && event.alerts.some((alert) => alert.code === "VOLTAGE_FLUCTUATION")
    || (voltage != null && voltage !== 0 && (voltage < VOLTAGE_NORMAL_MIN_V || voltage > VOLTAGE_NORMAL_MAX_V));
  if (denied || criticalTemperature || powerFailure) return { color: new THREE.Color("#ff3159"), intensity: 3.5 };
  if (voltageFluctuation) return { color: new THREE.Color("#ffad42"), intensity: 2.4 };
  if (type === "temperatura" || type === "voltaje" || event.temperature_c != null || event.voltage_v != null) {
    return { color: new THREE.Color("#3bffad"), intensity: 1.65 };
  }
  return { color: new THREE.Color("#39d7ff"), intensity: 1.2 };
}
