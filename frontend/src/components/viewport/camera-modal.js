import { CAMERA_STREAMS } from "./camera-config.js";

export function createCameraModal() {
  const dialog = document.querySelector("#camera-dialog");
  const video = document.querySelector("#camera-video");
  const placeholder = document.querySelector("#camera-no-signal");
  const title = document.querySelector("#camera-title");
  const locationLabel = document.querySelector("#camera-modal-location");
  const state = document.querySelector("#camera-stream-state");
  let currentCamera = null;
  const listeners = new AbortController();

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

  function open(camera, streamUrlOverride) {
    currentCamera = camera;
    title.textContent = `Cámara ${camera.id} · ${camera.shortName}`;
    locationLabel.textContent = camera.location;
    const streamUrl = streamUrlOverride || CAMERA_STREAMS[camera.id];
    video.classList.remove("is-live");
    placeholder.hidden = false;
    video.pause();
    video.removeAttribute("src");
    if (streamUrl) {
      video.src = streamUrl;
      setState("CONECTANDO", false);
      video.load();
      video.play().catch(() => {});
    } else {
      setState("SIN TRANSMISIÓN", false);
    }
    if (!dialog.open) dialog.showModal();
  }

  function stopStream() {
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
}
