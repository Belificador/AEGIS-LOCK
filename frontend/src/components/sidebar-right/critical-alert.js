import { getVoltageReading, VOLTAGE_NORMAL_MAX_V, VOLTAGE_NORMAL_MIN_V } from "../../voltage-reading.js";

const ACKED_KEY = "aegis.acknowledged-alerts.v1";
let sharedAudioContext = null;

export function primeAlertAudio() {
  if (typeof window === "undefined") return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;
  try {
    sharedAudioContext ||= new AudioContextClass();
    void sharedAudioContext.resume();
  } catch {
    // The visual alarm remains active if audio is unavailable.
  }
}

export function mountCriticalAlert({ onAcknowledge } = {}) {
  const dialog = document.createElement("dialog");
  dialog.className = "critical-alert-dialog";
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "critical-alert-title");
  dialog.setAttribute("aria-describedby", "critical-alert-message");
  dialog.innerHTML = `
    <div class="critical-alert-card">
      <span class="critical-alert-symbol" aria-hidden="true"><svg viewBox="0 0 48 48"><path d="M24 5 45 42H3L24 5Z"></path><path d="M24 17v12m0 6h.02"></path></svg></span>
      <p class="critical-alert-kicker"><i></i> ALERTA CRÍTICA · AEGIS LOCK</p>
      <h2 id="critical-alert-title">INTRUSIÓN DETECTADA</h2>
      <p id="critical-alert-message"></p>
      <p class="critical-alert-zone" data-zone></p>
      <button class="critical-alert-ack" type="button">🔕 SILENCIAR / ACUSAR RECIBO</button>
      <span class="critical-alert-count" data-count></span>
    </div>`;
  document.body.append(dialog);

  const title = dialog.querySelector("#critical-alert-title");
  const message = dialog.querySelector("#critical-alert-message");
  const zoneLabel = dialog.querySelector("[data-zone]");
  const countLabel = dialog.querySelector("[data-count]");
  const queue = [];
  const acked = loadAcknowledged();
  let current = null;
  let alarm = null;
  let disposed = false;

  function ingest(payload) {
    const event = payload?.event || payload || {};
    const alerts = Array.isArray(payload?.alerts) ? payload.alerts : [];
    clearResolvedState(event);
    const type = String(event.tipo_evento || "").toLowerCase();
    const value = String(event.valor ?? "").toUpperCase();
    const voltageReading = getVoltageReading(event);
    const deniedAccess = type === "acceso_pin" && ["DENIED", "LOCKOUT"].includes(value);
    const candidates = alerts
      .filter((alert) => (alert.severity === "critical" || alert.severity === "lockdown")
        && (alert.code !== "POWER_LOSS" || voltageReading === 0))
      .map((alert) => ({
        code: alert.code || "CRITICAL",
        message: alert.message || "Incidente crítico",
        oneShot: deniedAccess && alert.code === "INTRUSION",
      }));

    if (deniedAccess && !candidates.some((candidate) => candidate.code === "INTRUSION")) {
      candidates.push({ code: "INTRUSION", message: value === "LOCKOUT" ? "Bloqueo por intentos de acceso fallidos" : "Acceso denegado" , oneShot: true });
    }
    if (event.intrusion === true && !candidates.some((candidate) => candidate.code === "INTRUSION")) {
      candidates.push({ code: "INTRUSION", message: "Intrusión detectada" });
    }
    if (Number(event.temperature_c) > 38 && !candidates.some((candidate) => candidate.code === "HIGH_TEMPERATURE")) {
      candidates.push({ code: "HIGH_TEMPERATURE", message: `Temperatura crítica: ${event.temperature_c} °C` });
    }
    if (voltageReading === 0 && !candidates.some((candidate) => candidate.code === "POWER_LOSS")) {
      candidates.push({ code: "POWER_LOSS", message: "Se detectó una lectura de 0 V" });
    }

    const source = String(event.source_id || event.origen || "aegis");
    const zone = String(event.zone || event.zona || "GLOBAL");
    for (const candidate of candidates) {
      const eventId = String(event.event_id || "");
      const key = candidate.oneShot && eventId
        ? `${candidate.code}:${eventId}`
        : `${candidate.code}:${source}:${zone}`;
      if (acked.has(key) || queue.some((item) => item.key === key) || current?.key === key) continue;
      queue.push({ ...candidate, key, eventId, zone, source });
    }
    showNext();
  }

  function clearResolvedState(event) {
    const source = String(event.source_id || event.origen || "aegis");
    const zone = String(event.zone || event.zona || "GLOBAL");
    if ((event.tipo_evento === "temperatura" || event.temperature_c != null)
        && Number(event.temperature_c ?? event.valor) <= 38) acked.delete(`HIGH_TEMPERATURE:${source}:${zone}`);
    const voltage = getVoltageReading(event);
    if (voltage != null && voltage > 0) acked.delete(`POWER_LOSS:${source}:${zone}`);
    if (voltage != null && voltage >= VOLTAGE_NORMAL_MIN_V && voltage <= VOLTAGE_NORMAL_MAX_V) {
      acked.delete(`VOLTAGE_FLUCTUATION:${source}:${zone}`);
    }
    if (["GRANTED", "NORMAL", "CLEAR"].includes(String(event.valor ?? "").toUpperCase())
        || event.intrusion === false) acked.delete(`INTRUSION:${source}:${zone}`);
    saveAcknowledged(acked);
  }

  function showNext() {
    if (disposed || current || queue.length === 0) return;
    current = queue.shift();
    title.textContent = current.code === "INTRUSION" ? "INTRUSIÓN DETECTADA" : current.code.replaceAll("_", " ");
    message.textContent = current.message;
    zoneLabel.textContent = `ZONA AFECTADA · ${current.zone}`;
    countLabel.textContent = queue.length ? `${queue.length + 1} INCIDENTES PENDIENTES` : "ATENCIÓN REQUERIDA";
    document.documentElement.classList.add("critical-alert-active");
    if (!dialog.open) dialog.showModal();
    startAlarm();
  }

  function startAlarm() {
    primeAlertAudio();
    if (!sharedAudioContext || alarm) return;
    try {
      const gain = sharedAudioContext.createGain();
      gain.gain.value = 0.055;
      gain.connect(sharedAudioContext.destination);
      const oscillator = sharedAudioContext.createOscillator();
      oscillator.type = "sawtooth";
      oscillator.frequency.value = 880;
      oscillator.connect(gain);
      oscillator.start();
      let high = true;
      const timer = window.setInterval(() => {
        high = !high;
        oscillator.frequency.setTargetAtTime(high ? 880 : 620, sharedAudioContext.currentTime, 0.03);
      }, 320);
      alarm = { oscillator, gain, timer };
    } catch {
      alarm = null;
    }
  }

  function stopAlarm() {
    if (!alarm) return;
    window.clearInterval(alarm.timer);
    try { alarm.oscillator.stop(); } catch { /* already stopped */ }
    alarm.oscillator.disconnect();
    alarm.gain.disconnect();
    alarm = null;
  }

  dialog.querySelector(".critical-alert-ack").addEventListener("click", async () => {
    if (!current) return;
    stopAlarm();
    acked.add(current.key);
    saveAcknowledged(acked);
    try { await onAcknowledge?.(current, { hasPending: queue.length > 0 }); } catch { /* keep local acknowledgement responsive */ }
    current = null;
    dialog.close();
    document.documentElement.classList.remove("critical-alert-active");
    window.setTimeout(showNext, 120);
  });
  dialog.addEventListener("cancel", (event) => event.preventDefault());
  dialog.addEventListener("close", () => {
    if (current) dialog.showModal();
  });

  function dispose() {
    disposed = true;
    stopAlarm();
    queue.length = 0;
    current = null;
    document.documentElement.classList.remove("critical-alert-active");
    if (dialog.open) dialog.close();
    dialog.remove();
  }

  return { ingest, dispose };
}

function loadAcknowledged() {
  try {
    const values = JSON.parse(sessionStorage.getItem(ACKED_KEY) || "[]");
    return new Set(Array.isArray(values) ? values.filter((value) => typeof value === "string").slice(-200) : []);
  } catch {
    return new Set();
  }
}

function saveAcknowledged(acked) {
  try { sessionStorage.setItem(ACKED_KEY, JSON.stringify([...acked].slice(-200))); } catch { /* ignore storage quota */ }
}
