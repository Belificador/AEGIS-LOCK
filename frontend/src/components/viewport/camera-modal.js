import { CAMERA_STREAMS } from "./camera-config.js";

const AUTH_URL = import.meta.env.VITE_AUTH_API_URL || "https://aegis-lock-api.onrender.com/api/login";
const API_ROOT = AUTH_URL.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");
const CAMERA_LOAD_TIMEOUT_MS = 12_000;

export function createCameraModal({ session, cameras = [], onAvailability = () => {}, onSelection = () => {} } = {}) {
  const dialog = document.querySelector("#camera-dialog");
  const video = document.querySelector("#camera-video");
  const placeholder = document.querySelector("#camera-no-signal");
  const title = document.querySelector("#camera-title");
  const locationLabel = document.querySelector("#camera-modal-location");
  const state = document.querySelector("#camera-stream-state");
  const overlayName = document.querySelector("#camera-overlay-name");
  const overlayLocation = document.querySelector("#camera-overlay-location");
  const overlayTime = document.querySelector("#camera-overlay-time");
  const sequenceLabel = document.querySelector("#camera-sequence");
  const previousButton = document.querySelector("#camera-previous");
  const nextButton = document.querySelector("#camera-next");
  const fullscreenButton = document.querySelector("#camera-fullscreen");
  const listeners = new AbortController();
  const channels = normalizeChannels(cameras);
  const inactiveChannels = new Set();
  let currentCamera = null;
  let selectedIndex = -1;
  let requestSequence = 0;
  let navigationSequence = 0;
  let settleLoad = null;
  let loadTimer = null;
  let clockTimer = null;

  video.addEventListener("canplay", () => {
    if (Number(video.dataset.requestId) !== requestSequence) return;
    video.classList.add("is-live");
    placeholder.hidden = true;
    inactiveChannels.delete(currentCamera?.id);
    onAvailability(currentCamera?.id, true);
    onSelection(currentCamera, video.currentSrc || video.src);
    setState("TRANSMISIÓN DISPONIBLE", true);
    settleLoad?.(true);
  }, { signal: listeners.signal });
  video.addEventListener("error", () => {
    if (Number(video.dataset.requestId) !== requestSequence) return;
    video.classList.remove("is-live");
    placeholder.hidden = false;
    inactiveChannels.add(currentCamera?.id);
    onAvailability(currentCamera?.id, false);
    setState("CANAL SIN SEÑAL", false);
    settleLoad?.(false);
  }, { signal: listeners.signal });

  document.querySelectorAll('[data-close-dialog="camera-dialog"]').forEach((button) => {
    button.addEventListener("click", () => dialog.close(), { signal: listeners.signal });
  });
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }, { signal: listeners.signal });
  dialog.addEventListener("close", stopStream, { signal: listeners.signal });
  previousButton.addEventListener("click", () => { void cycle(-1); }, { signal: listeners.signal });
  nextButton.addEventListener("click", () => { void cycle(1); }, { signal: listeners.signal });
  fullscreenButton.addEventListener("click", toggleFullscreen, { signal: listeners.signal });
  document.addEventListener("fullscreenchange", updateFullscreenButton, { signal: listeners.signal });

  function setState(message, live) {
    state.replaceChildren();
    const led = document.createElement("i");
    led.className = `status-led ${live ? "led-normal" : "led-offline"}`;
    state.append(led, document.createTextNode(` ${message}`));
  }

  function updateClock() {
    const time = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date());
    overlayTime.textContent = time;
  }

  function updateSelectionLabels() {
    if (!currentCamera) return;
    const label = currentCamera.shortName || currentCamera.id;
    title.textContent = `Cámara ${label}`;
    overlayName.textContent = label;
    overlayLocation.textContent = currentCamera.location || currentCamera.zone || "Ubicación pendiente";
    locationLabel.textContent = overlayLocation.textContent;
    sequenceLabel.textContent = `${selectedIndex + 1} / ${channels.length}`;
  }

  async function open(camera, streamUrlOverride) {
    const cameraId = String(camera.cameraId || camera.id);
    let index = channels.findIndex((entry) => entry.id === cameraId);
    if (index < 0) {
      channels.push(normalizeCamera({ ...camera, id: cameraId, cameraId }));
      index = channels.length - 1;
    }
    if (!dialog.open) {
      dialog.showModal();
      updateClock();
      clockTimer = window.setInterval(updateClock, 1000);
    }
    const navigationId = ++navigationSequence;
    return selectAt(index, 1, navigationId, streamUrlOverride);
  }

  async function cycle(direction) {
    if (!channels.length) return;
    const nextIndex = selectedIndex < 0 ? (direction > 0 ? 0 : channels.length - 1) : (selectedIndex + direction + channels.length) % channels.length;
    const navigationId = ++navigationSequence;
    await selectAt(nextIndex, direction, navigationId);
  }

  async function selectAt(startIndex, direction, navigationId, firstUrlOverride) {
    for (let offset = 0; offset < channels.length; offset += 1) {
      if (navigationId !== navigationSequence || !dialog.open) return null;
      const index = (startIndex + offset * direction + channels.length * 2) % channels.length;
      const camera = channels[index];
      if (offset > 0 && inactiveChannels.has(camera.id)) continue;
      const feedUrl = offset === 0 ? firstUrlOverride : null;
      const result = await loadChannel(camera, index, feedUrl);
      if (result) return result;
    }
    setState("NO HAY MÁS CÁMARAS ACTIVAS", false);
    return null;
  }

  async function loadChannel(camera, index, streamUrlOverride) {
    finishLoad(false);
    const requestId = ++requestSequence;
    selectedIndex = index;
    currentCamera = camera;
    updateSelectionLabels();
    video.pause();
    video.removeAttribute("src");
    video.classList.remove("is-live");
    video.dataset.requestId = String(requestId);
    placeholder.hidden = false;
    setState("CONECTANDO", false);

    let feedUrl = streamUrlOverride;
    try {
      if (!feedUrl && session?.access_token) feedUrl = await getSignedFeedUrl(camera.id);
      if (!feedUrl) feedUrl = CAMERA_STREAMS[camera.numericId] || CAMERA_STREAMS[camera.id];
    } catch {
      feedUrl = CAMERA_STREAMS[camera.numericId] || CAMERA_STREAMS[camera.id];
    }
    if (requestId !== requestSequence || !dialog.open) return false;
    if (!feedUrl) {
      inactiveChannels.add(camera.id);
      onAvailability(camera.id, false);
      setState("SIN TRANSMISIÓN CONFIGURADA", false);
      return false;
    }

    const ready = new Promise((resolve) => { settleLoad = resolve; });
    loadTimer = window.setTimeout(() => {
      if (requestId !== requestSequence) return;
      inactiveChannels.add(camera.id);
      onAvailability(camera.id, false);
      setState("TIEMPO DE ESPERA AGOTADO", false);
      finishLoad(false);
    }, CAMERA_LOAD_TIMEOUT_MS);
    video.loop = true;
    video.src = feedUrl;
    video.load();
    video.play().catch(() => {});
    return ready.then((available) => available ? feedUrl : null);
  }

  function finishLoad(available) {
    if (loadTimer !== null) window.clearTimeout(loadTimer);
    loadTimer = null;
    const settle = settleLoad;
    settleLoad = null;
    settle?.(available);
  }

  function stopStream() {
    navigationSequence += 1;
    requestSequence += 1;
    finishLoad(false);
    window.clearInterval(clockTimer);
    clockTimer = null;
    video.pause();
    video.removeAttribute("src");
    video.load();
    video.classList.remove("is-live");
    placeholder.hidden = false;
    currentCamera = null;
    selectedIndex = -1;
    if (document.fullscreenElement === dialog) void document.exitFullscreen?.();
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === dialog) await document.exitFullscreen();
      else await dialog.requestFullscreen();
    } catch {
      setState("PANTALLA COMPLETA NO DISPONIBLE", false);
    }
  }

  function updateFullscreenButton() {
    const active = document.fullscreenElement === dialog;
    fullscreenButton.setAttribute("aria-label", active ? "Salir de pantalla completa" : "Activar pantalla completa");
    fullscreenButton.title = active ? "Salir de pantalla completa" : "Pantalla completa";
    fullscreenButton.textContent = active ? "⤢" : "⛶";
  }

  return {
    open,
    close: () => dialog.close(),
    dispose() { listeners.abort(); stopStream(); },
    get selected() { return currentCamera; },
  };

  async function getSignedFeedUrl(cameraId) {
    const response = await fetch(`${API_ROOT}/api/v1/cameras/${encodeURIComponent(cameraId)}/feed-url`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "No se pudo obtener el feed de la cámara.");
    return payload.feed_url || null;
  }
}

function normalizeChannels(cameras) {
  return cameras.map((camera) => normalizeCamera(camera));
}

function normalizeCamera(camera) {
  const id = String(camera.cameraId || camera.id || "");
  const numericId = Number(camera.numericId || /^CAM_(\d+)_/.exec(id)?.[1]) || null;
  const shortName = camera.shortName || id.replace(/^CAM_\d+_/, "").replaceAll("_", " ");
  return { ...camera, id, cameraId: id, numericId, shortName, location: camera.location || camera.zone || "Ubicación pendiente" };
}
