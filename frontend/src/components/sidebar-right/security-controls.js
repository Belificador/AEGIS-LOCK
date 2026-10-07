import { CAMERA_MARKERS } from "../viewport/camera-markers.js";

const SCHEDULE_KEY = "aegis.closeSchedule.v1";
const MODE_KEY = "aegis.localMode.v1";

export function mountSecurityControls(root, { role, onModeChange, onOpenCamera, tacticalDockRoot }) {
  root.innerHTML = `
    <section class="panel-card security-panel" aria-labelledby="security-title">
      <div class="panel-heading"><span id="security-title">Control de seguridad</span><small>SIM / LOCAL</small></div>
      <div class="security-mode-banner"><i class="status-led led-warning"></i><span><small>ESTADO ACTUAL</small><strong>SIMULACIÓN LOCAL</strong></span><b>DEMO</b></div>
      <p class="security-subtitle">Protocolos tácticos de demostración. Sin conexión a cerraduras ni actuadores.</p>
      <div class="schedule-block">
        <div class="panel-heading schedule-heading"><span>Cierre de jornada</span><small>CIERRE PROGRAMADO</small></div>
        <div class="schedule-row"><label class="visually-hidden" for="close-time">Hora de cierre</label><input id="close-time" type="time" value="18:00" /><button id="schedule-toggle" class="schedule-button" type="button">PROGRAMAR CIERRE</button></div>
        <p id="schedule-status" class="schedule-status">Sin cierre automático programado.</p>
      </div>
      <button id="release-system" class="release-button" type="button">LIBERAR / VOLVER A NORMAL</button>
      <p class="mode-simulation-note">PROTOTIPO LOCAL · SIN CONTROL DE ACCESO FÍSICO</p>
    </section>
    <section class="panel-card selected-camera-panel" aria-labelledby="selected-camera-title">
      <div class="panel-heading"><span id="selected-camera-title">Canales de cámara</span><small id="camera-channel-state">ESPERANDO MODELO</small></div>
      <div id="camera-channel-list" class="camera-channel-list" aria-label="Canales disponibles"></div>
      <button id="selected-camera-preview" class="selected-camera-player" type="button" disabled aria-label="Abrir cámara seleccionada">
        <video id="selected-camera-video" autoplay muted playsinline loop crossorigin="anonymous" hidden></video>
        <div class="camera-placeholder" aria-hidden="true"><i></i><span></span><span></span><span></span></div>
        <div class="camera-preview-overlay"><span class="camera-preview-live"><i class="status-led led-offline"></i><b id="camera-preview-state">SIN SEÑAL</b></span><strong id="camera-preview-name">Selecciona una cámara</strong><time id="camera-preview-time">--:--:--</time></div>
      </button>
      <p class="camera-side-location">Modelo no conectado. Los canales aparecerán al recibir telemetría real.</p>
    </section>`;

  const scheduleInput = root.querySelector("#close-time");
  const toggle = root.querySelector("#schedule-toggle");
  const status = root.querySelector("#schedule-status");
  const release = root.querySelector("#release-system");
  const cameraPreview = root.querySelector("#selected-camera-preview");
  const cameraPreviewName = root.querySelector("#camera-preview-name");
  const cameraPreviewState = root.querySelector("#camera-preview-state");
  const cameraPreviewTime = root.querySelector("#camera-preview-time");
  const cameraChannelList = root.querySelector("#camera-channel-list");
  const cameraChannelState = root.querySelector("#camera-channel-state");
  const cameraLocation = root.querySelector(".camera-side-location");
  const lockdownDialog = document.querySelector("#lockdown-confirmation");
  const cancelLockdown = lockdownDialog.querySelector("#cancel-lockdown");
  const dismissLockdown = lockdownDialog.querySelector("#dismiss-lockdown");
  const confirmLockdown = lockdownDialog.querySelector("#confirm-lockdown");
  const lockdownButton = document.createElement("button");
  lockdownButton.id = "lockdown-button";
  lockdownButton.className = "security-button lockdown-button";
  lockdownButton.type = "button";
  lockdownButton.innerHTML = '<span class="security-button-icon" aria-hidden="true">▣</span><span class="lockdown-label">ACTIVAR MODO LOCKDOWN</span><b aria-hidden="true">↗</b>';
  const evacuationButton = document.createElement("button");
  evacuationButton.id = "evacuation-button";
  evacuationButton.className = "security-button evacuation-button";
  evacuationButton.type = "button";
  evacuationButton.innerHTML = '<span class="security-button-icon" aria-hidden="true">⚠</span><span>ACTIVAR MODO / EVACUACIÓN</span>';
  (tacticalDockRoot || root.querySelector(".security-panel")).append(lockdownButton, evacuationButton);
  const cameraVideo = root.querySelector("#selected-camera-video");
  const cameraPlaceholder = root.querySelector(".camera-placeholder");
  let selectedCameraId = null;
  let selectedCamera = null;
  const cameraChannelNodes = new Map();

  for (const camera of CAMERA_MARKERS) {
    const number = Number(/^CAM_(\d+)_/.exec(camera.cameraId)?.[1]);
    const shortName = camera.cameraId.replace(/^CAM_\d+_/, "").replaceAll("_", " ");
    const channel = document.createElement("button");
    channel.type = "button";
    channel.className = "camera-channel-button";
    channel.dataset.cameraId = camera.cameraId;
    channel.dataset.availability = "unknown";
    channel.setAttribute("aria-label", `Abrir cámara ${number}: ${camera.zone}`);
    const code = document.createElement("span");
    code.className = "camera-channel-code";
    code.textContent = `CAM ${String(number).padStart(2, "0")}`;
    const name = document.createElement("strong");
    name.textContent = shortName;
    const led = document.createElement("i");
    led.className = "status-led led-offline";
    led.setAttribute("aria-hidden", "true");
    channel.append(code, name, led);
    channel.addEventListener("click", () => onOpenCamera?.({ ...camera, id: camera.cameraId, numericId: number, shortName, location: camera.zone }));
    cameraChannelList.append(channel);
    cameraChannelNodes.set(camera.cameraId, channel);
  }

  cameraPreview.addEventListener("click", () => {
    if (selectedCamera) onOpenCamera?.(selectedCamera);
  });
  cameraVideo.addEventListener("canplay", () => {
    cameraChannelState.textContent = `CÁMARA ${selectedCameraId} · EN VIVO`;
    cameraPreviewState.textContent = "EN VIVO";
    cameraPreview.querySelector(".status-led").className = "status-led led-normal";
    cameraChannelNodes.get(selectedCameraId)?.setAttribute("data-availability", "active");
    cameraLocation.textContent = `${cameraLocation.dataset.location || ""} · TRANSMISIÓN DISPONIBLE`;
  });
  cameraVideo.addEventListener("error", () => {
    cameraChannelState.textContent = `CÁMARA ${selectedCameraId || "—"} · SIN SEÑAL`;
    cameraPreviewState.textContent = "SIN SEÑAL";
    cameraPreview.querySelector(".status-led").className = "status-led led-offline";
    cameraChannelNodes.get(selectedCameraId)?.setAttribute("data-availability", "inactive");
    cameraLocation.textContent = "El feed asignado no está disponible.";
  });
  const updateCameraClock = () => { cameraPreviewTime.textContent = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()); };
  updateCameraClock();
  const cameraClockTimer = window.setInterval(updateCameraClock, 1000);
  let schedule = readSchedule();
  let initialMode = readMode();

  const canOperate = ["admin", "operator"].includes(role);
  lockdownButton.disabled = !canOperate;
  evacuationButton.disabled = !canOperate;
  toggle.disabled = !canOperate;
  scheduleInput.disabled = !canOperate;
  if (!canOperate) {
    lockdownButton.title = "La activación está reservada a Operador o Administrador";
    evacuationButton.title = lockdownButton.title;
  }

  lockdownButton.addEventListener("click", () => lockdownDialog.showModal());
  dismissLockdown.addEventListener("click", () => lockdownDialog.close("cancel"));
  lockdownDialog.addEventListener("click", (event) => {
    if (event.target === lockdownDialog) lockdownDialog.close("cancel");
  });
  cancelLockdown.addEventListener("click", () => lockdownDialog.close("cancel"));
  confirmLockdown.addEventListener("click", () => {
    lockdownDialog.close("confirm");
    setMode("LOCKDOWN", "ACTIVACIÓN MANUAL");
  });
  evacuationButton.addEventListener("click", () => {
    if (window.confirm("¿Activar el estado de evacuación simulado? No se enviará ningún comando físico.")) setMode("EVACUACIÓN", "ACTIVACIÓN MANUAL");
  });
  toggle.addEventListener("click", () => {
    if (schedule?.enabled) {
      schedule = null;
      localStorage.removeItem(SCHEDULE_KEY);
      renderSchedule();
      return;
    }
    schedule = { enabled: true, time: scheduleInput.value || "18:00", activatedDate: null };
    localStorage.setItem(SCHEDULE_KEY, JSON.stringify(schedule));
    renderSchedule();
    checkSchedule();
  });
  release.disabled = role !== "admin";
  release.title = role === "admin" ? "Solo restablece el estado simulado" : "La liberación está reservada al perfil Administrador";
  release.addEventListener("click", () => {
    if (role !== "admin") return;
    if (schedule?.enabled) {
      schedule.activatedDate = localDateKey(new Date());
      localStorage.setItem(SCHEDULE_KEY, JSON.stringify(schedule));
    }
    setMode("NORMAL", "LIBERACIÓN ADMINISTRADOR");
  });

  function renderSchedule() {
    const enabled = Boolean(schedule?.enabled);
    toggle.textContent = enabled ? "CANCELAR CIERRE" : "PROGRAMAR CIERRE";
    scheduleInput.value = enabled ? schedule.time : scheduleInput.value || "18:00";
    scheduleInput.disabled = enabled || !canOperate;
    status.textContent = enabled ? `Cierre local programado diariamente a las ${schedule.time}.` : "Sin cierre automático programado.";
  }

  function checkSchedule() {
    if (!schedule?.enabled) return;
    const now = new Date();
    const today = localDateKey(now);
    const [hours, minutes] = schedule.time.split(":").map(Number);
    if ((now.getHours() * 60 + now.getMinutes()) >= hours * 60 + minutes && schedule.activatedDate !== today) {
      schedule.activatedDate = today;
      localStorage.setItem(SCHEDULE_KEY, JSON.stringify(schedule));
      setMode("LOCKDOWN", "CIERRE PROGRAMADO");
    }
  }

  function setMode(mode, source) {
    initialMode = { mode, source };
    localStorage.setItem(MODE_KEY, JSON.stringify(initialMode));
    onModeChange(mode, source);
  }

  renderSchedule();

  function updateCamera(event) {
    const metadata = event.metadata || {};
    const camera = metadata.camera && typeof metadata.camera === "object" ? metadata.camera : {};
    const id = metadata.camera_id || metadata.cameraId || camera.id || event.valor || "EXT";
    const location = metadata.location || metadata.ubicacion || camera.location || event.zona || "Ubicación recibida del emisor";
    const feedUrl = metadata.feed_url || metadata.stream_url || metadata.video_url || metadata.feed;
    selectedCameraId = id;
    const marker = CAMERA_MARKERS.find((item) => item.cameraId === id);
    selectedCamera = marker
      ? { ...marker, id, cameraId: id, numericId: Number(/^CAM_(\d+)_/.exec(id)?.[1]), shortName: id.replace(/^CAM_\d+_/, "").replaceAll("_", " "), location }
      : { id, cameraId: id, numericId: Number(/^CAM_(\d+)_/.exec(id)?.[1]), shortName: id, zone: location, location };
    cameraPreview.disabled = false;
    cameraPreviewName.textContent = selectedCamera.shortName;
    cameraPreview.setAttribute("aria-label", `Abrir cámara ${selectedCamera.shortName} en pantalla completa`);
    cameraLocation.dataset.location = location;
    cameraChannelState.textContent = `CÁMARA ${id} · ${feedUrl ? "CONECTANDO" : "SELECCIONADA"}`;
    cameraPreviewState.textContent = feedUrl ? "CONECTANDO" : "SELECCIONADA";
    cameraPreview.querySelector(".status-led").className = "status-led led-warning";
    cameraLocation.textContent = `${location} · ${feedUrl ? "CONECTANDO AL FEED" : "Toca para abrir la transmisión"}`;
    for (const [cameraId, channel] of cameraChannelNodes) channel.classList.toggle("is-selected", cameraId === id);
    cameraChannelNodes.get(id)?.setAttribute("data-availability", feedUrl ? "loading" : "unknown");
    cameraVideo.pause();
    cameraVideo.removeAttribute("src");
    cameraVideo.hidden = !feedUrl;
    cameraPlaceholder.hidden = Boolean(feedUrl);
    if (feedUrl) {
      cameraVideo.src = feedUrl;
      cameraVideo.load();
      cameraVideo.play().catch(() => {});
    }
  }

  function setCameraAvailability(cameraId, available) {
    cameraChannelNodes.get(cameraId)?.setAttribute("data-availability", available ? "active" : "inactive");
  }

  return { initialMode, checkSchedule, updateCamera, setCameraAvailability, destroy() {
    window.clearInterval(cameraClockTimer);
    cameraVideo.pause();
    cameraVideo.removeAttribute("src");
    cameraVideo.load();
  }, setMode(mode) {
    lockdownButton.classList.toggle("is-lockdown", mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA");
    lockdownButton.querySelector(".lockdown-label").textContent = mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA"
      ? "LOCKDOWN SIMULADO ACTIVO"
      : "ACTIVAR MODO LOCKDOWN";
    evacuationButton.classList.toggle("is-evacuating", mode === "EVACUACIÓN");
    evacuationButton.setAttribute("aria-pressed", String(mode === "EVACUACIÓN"));
    evacuationButton.querySelector("span:last-child").textContent = mode === "EVACUACIÓN"
      ? "MODO EVACUACIÓN ACTIVO"
      : "ACTIVAR MODO / EVACUACIÓN";
  } };
}

function readSchedule() {
  try {
    const value = JSON.parse(localStorage.getItem(SCHEDULE_KEY) || "null");
    return value?.enabled && /^\d{2}:\d{2}$/.test(value.time) ? value : null;
  } catch {
    return null;
  }
}

function readMode() {
  try {
    const saved = JSON.parse(localStorage.getItem(MODE_KEY) || "null");
    if (["NORMAL", "ALERTA", "LOCKDOWN", "EVACUACIÓN"].includes(saved?.mode)) return saved;
  } catch {
    localStorage.removeItem(MODE_KEY);
  }
  return { mode: "NORMAL", source: "Simulación local" };
}

function localDateKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
