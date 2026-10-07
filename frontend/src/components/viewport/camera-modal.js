import { CAMERA_STREAMS } from "./camera-config.js";

const AUTH_URL = import.meta.env.VITE_AUTH_API_URL || "https://aegis-lock-api.onrender.com/api/login";
const API_ROOT = AUTH_URL.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");

export function createCameraModal({ session } = {}) {
  const dialog = document.querySelector("#camera-dialog");
  const video = document.querySelector("#camera-video");
  const placeholder = document.querySelector("#camera-no-signal");
  const title = document.querySelector("#camera-title");
  const locationLabel = document.querySelector("#camera-modal-location");
  const state = document.querySelector("#camera-stream-state");
  let currentCamera = null;
  const listeners = new AbortController();
  let requestSequence = 0;

  video.addEventListener("canplay", () => {
    video.classList.add("is-live");
    placeholder.hidden = true;
    setState("TRANSMISIÓN DISPONIBLE", true);
  }, { signal: listeners.signal });
  video.addEventListener("error", () => {
    video.classList.remove("is-live");
    placeholder.hidden = false;
    setState("ERROR DE TRANSMISIÓN", false);
  }, { signal: listeners.signal });

  document.querySelectorAll('[data-close-dialog="camera-dialog"]').forEach((button) => {
    button.addEventListener("click", () => dialog.close(), { signal: listeners.signal });
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }, { signal: listeners.signal });
  dialog.addEventListener("close", stopStream, { signal: listeners.signal });

  function setState(message, live) {
    state.replaceChildren();
    const led = document.createElement("i");
    led.className = `status-led ${live ? "led-normal" : "led-offline"}`;
    state.append(led, document.createTextNode(` ${message}`));
  }

  async function open(camera, streamUrlOverride) {
    currentCamera = camera;
    title.textContent = `Cámara ${camera.id} · ${camera.shortName}`;
    locationLabel.textContent = camera.location;
    const requestId = ++requestSequence;
    video.classList.remove("is-live");
    placeholder.hidden = false;
    video.pause();
    video.removeAttribute("src");
    setState("CONECTANDO", false);
    if (!dialog.open) dialog.showModal();

    try {
      let streamUrl = streamUrlOverride;
      if (!streamUrl && session?.access_token) streamUrl = await getSignedFeedUrl(camera.id);
      if (!streamUrl) streamUrl = CAMERA_STREAMS[camera.numericId] || CAMERA_STREAMS[camera.id];
      if (requestId !== requestSequence || !dialog.open) return null;
      if (!streamUrl) {
        setState("SIN TRANSMISIÓN CONFIGURADA", false);
        return null;
      }
      video.loop = true;
      video.src = streamUrl;
      video.load();
      video.play().catch(() => {});
      return streamUrl;
    } catch {
      if (requestId === requestSequence && dialog.open) setState("NO SE PUDO CONECTAR AL FEED", false);
      return null;
    }
  }

  function stopStream() {
    requestSequence += 1;
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.classList.remove("is-live");
    placeholder.hidden = false;
    currentCamera = null;
  }

  return {
    open,
    close: () => dialog.close(),
    dispose() { listeners.abort(); stopStream(); },
    get selected() { return currentCamera; },
  };

  async function getSignedFeedUrl(cameraId) {
    if (!session?.access_token) return null;
    const response = await fetch(`${API_ROOT}/api/v1/cameras/${encodeURIComponent(cameraId)}/feed-url`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No se pudo obtener el feed de la cámara.");
    return payload.feed_url || null;
  }
}
