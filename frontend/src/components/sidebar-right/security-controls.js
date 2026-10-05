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
      <div class="panel-heading"><span id="selected-camera-title">Canales de cámara</span><small>ESPERANDO MODELO</small></div>
      <div class="camera-placeholder" aria-hidden="true"><i></i><span></span><span></span><span></span></div>
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
  let schedule = readSchedule();
  let initialMode = readMode();

  lockdownButton.addEventListener("click", () => lockdownDialog.showModal());
  cancelLockdown.addEventListener("click", () => lockdownDialog.close("cancel"));
  confirmLockdown.addEventListener("click", () => {
    lockdownDialog.close("confirm");
    setMode("LOCKDOWN", "ACTIVACIÓN MANUAL");
  });
  root.querySelector("#evacuation-button").addEventListener("click", () => {
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
  return { initialMode, checkSchedule, setMode(mode) {
    const button = root.querySelector("#lockdown-button");
    button.classList.toggle("is-lockdown", mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA");
    button.querySelector(".lockdown-label").textContent = mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA"
      ? "LOCKDOWN SIMULADO ACTIVO"
      : "ACTIVAR MODO LOCKDOWN";
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
