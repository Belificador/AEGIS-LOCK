export const HIDDEN_CAMERA_IDS = Object.freeze([
  "CAM_02_CONFERENCIAS",
  "CAM_05_OFICINA_L2",
]);

export function isCameraHidden(cameraId) {
  return HIDDEN_CAMERA_IDS.includes(String(cameraId || ""));
}
