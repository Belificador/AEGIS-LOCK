import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const MODEL_URL = new URL("../../models_3d/oficina/edificio.glb", import.meta.url).href;

export class Visor3D {
  constructor(container, { onLoad = () => {}, onError = () => {} } = {}) {
    this.container = container;
    this.onLoad = onLoad;
    this.onError = onError;
    this.destroyed = false;
    this.zoneEvents = new Map();
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
    this.camera.position.set(15, 12, 17);
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
      const center = bounds.getCenter(new THREE.Vector3());
      const size = bounds.getSize(new THREE.Vector3());
      const maxDimension = Math.max(size.x, size.y, size.z) || 1;
      this.model.position.sub(center);
      this.model.scale.setScalar(12 / maxDimension);
      this.scene.add(this.model);
      this.camera.position.set(15, 12, 17);
      this.controls.target.set(0, 0, 0);
      this.controls.update();
      this.applyZoneEvents();
      this.onLoad();
      this.resize();
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

  resize() {
    if (!this.container || !this.renderer) return;
    const { width, height } = this.container.getBoundingClientRect();
    if (width <= 0 || height <= 0) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
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
    this.controls.dispose();
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
  const powerFailure = (type === "voltaje" || event.voltage_v != null) && Number(event.voltage_v ?? event.valor) === 0;
  if (denied || criticalTemperature || powerFailure) return { color: new THREE.Color("#ff3159"), intensity: 3.5 };
  if (type === "temperatura" || type === "voltaje" || event.temperature_c != null || event.voltage_v != null) {
    return { color: new THREE.Color("#3bffad"), intensity: 1.65 };
  }
  return { color: new THREE.Color("#39d7ff"), intensity: 1.2 };
}
