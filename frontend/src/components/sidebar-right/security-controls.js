const SCHEDULE_KEY = "aegis.closeSchedule.v1";
const MODE_KEY = "aegis.localMode.v1";

export function mountSecurityControls(root, { role, onModeChange }) {
  root.innerHTML = `
    <section class="panel-card security-panel" aria-labelledby="security-title">
      <div class="panel-heading"><span id="security-title">Control de seguridad</span><small>SIM / LOCAL</small></div>
      <div class="security-mode-banner"><i class="status-led led-warning"></i><span><small>ESTADO ACTUAL</small><strong>SIMULACIÓN LOCAL</strong></span><b>DEMO</b></div>
      <p class="security-subtitle">Protocolos tácticos de demostración. Sin conexión a cerraduras ni actuadores.</p>
      <button id="lockdown-button" class="security-button lockdown-button" type="button"><span class="security-button-icon" aria-hidden="true">▣</span><span class="lockdown-label">ACTIVAR MODO LOCKDOWN</span><b aria-hidden="true">↗</b></button>
      <button id="evacuation-button" class="security-button evacuation-button" type="button"><span class="security-button-icon" aria-hidden="true">⚠</span><span>ACTIVAR MODO / EVACUACIÓN</span></button>
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
      <div class="selected-camera-player">
        <video id="selected-camera-video" controls autoplay muted playsinline crossorigin="anonymous" hidden></video>
        <div class="camera-placeholder" aria-hidden="true"><i></i><span></span><span></span><span></span></div>
      </div>
      <p class="camera-side-location">Modelo no conectado. Los canales aparecerán al recibir telemetría real.</p>
    </section>`;

  const scheduleInput = root.querySelector("#close-time");
  const toggle = root.querySelector("#schedule-toggle");
  const status = root.querySelector("#schedule-status");
  const release = root.querySelector("#release-system");
  const lockdownDialog = document.querySelector("#lockdown-confirmation");
  const cancelLockdown = lockdownDialog.querySelector("#cancel-lockdown");
  const confirmLockdown = lockdownDialog.querySelector("#confirm-lockdown");
  const lockdownButton = root.querySelector("#lockdown-button");
  const evacuationButton = root.querySelector("#evacuation-button");
  const cameraVideo = root.querySelector("#selected-camera-video");
  const cameraPlaceholder = root.querySelector(".camera-placeholder");
  let selectedCameraId = null;
  cameraVideo.addEventListener("canplay", () => {
    root.querySelector("#camera-channel-state").textContent = `CÁMARA ${selectedCameraId} · EN VIVO`;
    root.querySelector(".camera-side-location").textContent = `${root.querySelector(".camera-side-location").dataset.location || ""} · TRANSMISIÓN DISPONIBLE`;
  });
  cameraVideo.addEventListener("error", () => {
    root.querySelector("#camera-channel-state").textContent = `CÁMARA ${selectedCameraId || "—"} · SIN SEÑAL`;
    root.querySelector(".camera-side-location").textContent = "El feed asignado no está disponible.";
  });
  let schedule = readSchedule();
  let initialMode = readMode();

  lockdownButton.addEventListener("click", () => lockdownDialog.showModal());
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
    scheduleInput.disabled = enabled;
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
    const locationNode = root.querySelector(".camera-side-location");
    locationNode.dataset.location = location;
    root.querySelector("#camera-channel-state").textContent = `CÁMARA ${id} · ${feedUrl ? "CONECTANDO" : "SIN VIDEO"}`;
    locationNode.textContent = `${location} · ${feedUrl ? "CONECTANDO AL FEED" : "SIN VIDEO ASIGNADO"}`;
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

  return { initialMode, checkSchedule, updateCamera, destroy() {
    cameraVideo.pause();
    cameraVideo.removeAttribute("src");
    cameraVideo.load();
  }, setMode(mode) {
    const button = root.querySelector("#lockdown-button");
    button.classList.toggle("is-lockdown", mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA");
    button.querySelector(".lockdown-label").textContent = mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA"
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
