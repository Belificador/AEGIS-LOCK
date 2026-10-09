import NAV_GRID from "../../../../models_3d/nav/navgrid.json";

// Los nodos Sphere.* del GLB son luminarias. Estos marcadores explícitos se
// anclan a las zonas del navgrid y se mantienen editables por cámara.
export const CAMERA_MARKERS = Object.freeze([
  { cameraId: "CAM_01_GERENCIA", zone: "Administración", zoneId: 3, offset: [0, 0] },
  { cameraId: "CAM_02_CONFERENCIAS", zone: "Sala de Conferencias (aprox.)", zoneId: 4, offset: [-1.5, -1.6] },
  { cameraId: "CAM_03_OFICINA_L1", zone: "Oficina L1", zoneId: 1, offset: [0, 0] },
  { cameraId: "CAM_04_OFICINA_R1", zone: "Gerencia", zoneId: 2, offset: [0, 0] },
  { cameraId: "CAM_05_OFICINA_L2", zone: "Oficina L2 (aprox.)", zoneId: 1, offset: [1.8, 0.8] },
  { cameraId: "CAM_06_PASILLO_NORTE", zone: "Pasillo norte", zoneId: 0, offset: [0, -4.2] },
  { cameraId: "CAM_07_PASILLO_SUR", zone: "Pasillo sur", zoneId: 0, offset: [0, 4.2] },
  { cameraId: "CAM_08_RECEPCION", zone: "Recepción", zoneId: 4, offset: [1.4, 1.5] },
  { cameraId: "CAM_09_OFICINA_L3", zone: "Oficina L3", zoneId: 5, offset: [0, 0] },
]);

export function addCameraMarkers(THREE, model, displayScale, onSelect) {
  const zones = new Map((NAV_GRID.zones || []).map((zone) => [zone.id, zone]));
  const navScale = Number(NAV_GRID.transform?.scale) || 1;
  const positionX = Number(NAV_GRID.transform?.positionX) || 0;
  const positionY = Number(NAV_GRID.transform?.positionY) || 0;
  const positionZ = Number(NAV_GRID.transform?.positionZ) || 0;
  const targets = [];

  for (const camera of CAMERA_MARKERS) {
    const zone = zones.get(camera.zoneId);
    if (!zone?.centre) continue;
    const group = new THREE.Group();
    group.name = `camera-marker-${camera.cameraId}`;
    group.userData.camera = camera;
    group.position.set(
      (zone.centre[0] - positionX + camera.offset[0]) / navScale,
      (2.25 - positionY) / navScale,
      (zone.centre[1] - positionZ + camera.offset[1]) / navScale,
    );
    // El marcador conserva un tamaño visible aunque se escale el GLB para el visor.
    group.scale.setScalar(1 / displayScale);

    const texture = createCameraTexture(THREE, camera.cameraId);
    const icon = new THREE.Sprite(new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    }));
    icon.scale.set(0.8, 0.8, 1);
    icon.renderOrder = 1000;
    icon.userData.cameraMarker = group;
    group.add(icon);
    group.userData.icon = icon;
    model.add(group);
    targets.push(icon);
  }

  model.updateMatrixWorld(true);
  return {
    targets,
    dispose() {
      for (const target of targets) {
        target.material.map?.dispose();
        target.material.dispose();
        target.parent?.parent?.remove(target.parent);
      }
    },
    select(target) {
      const camera = target?.userData?.cameraMarker?.userData?.camera;
      if (camera) onSelect?.(camera);
      return camera || null;
    },
  };
}

function createCameraTexture(THREE, cameraId) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, 128, 128);
  context.fillStyle = "rgba(5, 15, 27, .94)";
  context.strokeStyle = "#42d9ff";
  context.lineWidth = 5;
  context.beginPath();
  context.arc(64, 64, 57, 0, Math.PI * 2);
  context.fill();
  context.stroke();
  context.fillStyle = "#42d9ff";
  context.fillRect(34, 40, 49, 39);
  context.beginPath();
  context.moveTo(83, 49);
  context.lineTo(101, 40);
  context.lineTo(101, 79);
  context.lineTo(83, 70);
  context.closePath();
  context.fill();
  context.fillStyle = "#06111d";
  context.beginPath();
  context.arc(58, 59, 10, 0, Math.PI * 2);
  context.fill();
  context.fillStyle = "#eafaff";
  context.font = "bold 17px monospace";
  context.textAlign = "center";
  context.fillText(cameraId.slice(4, 6), 64, 105);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
