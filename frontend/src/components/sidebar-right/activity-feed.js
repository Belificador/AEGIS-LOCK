import { getVoltageReading, VOLTAGE_NORMAL_MAX_V, VOLTAGE_NORMAL_MIN_V } from "../../voltage-reading.js";

const PRIORITY_RANK = { system: 0, success: 1, warning: 2, critical: 3 };

export function formatActivity(data, { priority, timestamp, alerts: suppliedAlerts } = {}) {
  const event = data?.event && typeof data.event === "object" ? data.event : data || {};
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const alerts = Array.isArray(suppliedAlerts) ? suppliedAlerts : Array.isArray(data?.alerts) ? data.alerts : [];
  const type = String(event.tipo_evento || event.event_type || data?.kind || "activity").trim().toLowerCase();
  const value = readableValue(event.valor);
  const location = readableLabel(
    metadata.door_name || metadata.location || metadata.ubicacion || event.door_name || event.zone || event.zona,
  );
  const camera = titleCase(readableLabel(metadata.name || metadata.camera_name || metadata.camera_id || event.camera_id || value));
  const winner = alerts.reduce((current, alert) => {
    const candidate = normalizePriority(alert.severity);
    const currentRank = current ? PRIORITY_RANK[current.severity] : -1;
    return PRIORITY_RANK[candidate] > currentRank ? { ...alert, severity: candidate } : current;
  }, null);

  let title = "Actividad del modelo";
  let detail = "";
  let inferredPriority = "system";

  if (data?.kind === "connection") {
    title = "Conexión del modelo";
    detail = connectionMessage(data.status || data.detail);
  } else if (data?.kind === "activity_alert") {
    title = readableLabel(data.title || "Alerta de seguridad");
    detail = readableLabel(data.message || "Requiere atención");
  } else if (data?.kind === "error") {
    title = "Error de comunicación";
    detail = readableLabel(data.detail || event.message || "No se pudo recibir la señal del modelo");
    inferredPriority = "critical";
  } else if (data?.kind === "message") {
    title = "Mensaje del modelo";
    detail = readableLabel(data.raw?.message || data.raw?.detail || "Mensaje recibido");
  } else if (data?.kind === "local_mode" || type === "local_mode") {
    const mode = String(event.mode || event.value || "NORMAL").toUpperCase();
    title = mode === "NORMAL" ? "Sistema liberado"
      : mode === "EVACUACIÓN" ? "Modo de evacuación"
        : mode === "ALERTA" ? "Alerta activada"
          : mode === "LOCKDOWN" ? "Lockdown activado"
            : "Cierre de jornada";
    detail = `${mode === "NORMAL" ? "Liberado" : "Activado"} por ${readableLabel(event.actor || "Administrador")}`;
    if (event.source && event.source !== event.actor) detail += ` · ${readableLabel(event.source)}`;
    inferredPriority = mode === "EVACUACIÓN" || mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA" || mode === "ALERTA" ? "warning" : "system";
  } else if (["acceso_pin", "access_pin"].includes(type)) {
    const result = value.toUpperCase();
    title = result === "GRANTED" || result === "AUTHORIZED" ? "Acceso autorizado" : result === "LOCKOUT" ? "Acceso bloqueado" : "Acceso denegado";
    detail = `${location || "Puerta principal"} · PIN temporal`;
    inferredPriority = result === "GRANTED" || result === "AUTHORIZED" ? "success" : "critical";
  } else if (["movimiento", "movement", "movement_detected", "motion", "motion_detected", "deteccion_movimiento", "detección_movimiento", "movimiento_detectado"].includes(type)) {
    title = "Movimiento detectado";
    detail = camera ? `Cámara ${camera}` : location ? `Zona ${location}` : "Sensor de movimiento";
    inferredPriority = "warning";
  } else if (type === "camera_selected") {
    title = "Cámara seleccionada";
    detail = camera ? `Cámara ${camera}${location ? ` · ${location}` : ""}` : location || "Vista de cámara actualizada";
  } else if (["lockdown", "cierre_jornada", "end_of_day"].includes(type) || event.lockdown) {
    title = "Cierre de jornada";
    detail = `Activado por ${readableLabel(event.actor || event.source_id || event.origen || "Administrador")}`;
    inferredPriority = "warning";
  } else if (["temperatura", "temperature"].includes(type) || event.temperature_c != null) {
    const temperature = Number(event.temperature_c ?? value);
    title = temperature > 38 ? "Temperatura crítica" : "Temperatura actualizada";
    detail = `${Number.isFinite(temperature) ? `${temperature.toLocaleString("es", { maximumFractionDigits: 1 })} °C` : value}${location ? ` · ${location}` : ""}`;
    inferredPriority = temperature > 38 ? "critical" : "system";
  } else if (["voltaje", "voltage"].includes(type) || event.voltage_v != null) {
    const voltage = getVoltageReading(event);
    const fluctuating = alerts.some((alert) => alert.code === "VOLTAGE_FLUCTUATION")
      || (voltage != null && voltage !== 0 && (voltage < VOLTAGE_NORMAL_MIN_V || voltage > VOLTAGE_NORMAL_MAX_V));
    title = voltage == null ? "Voltaje sin lectura" : voltage === 0 ? "Corte de energía" : fluctuating ? "Fluctuación de voltaje" : "Voltaje actualizado";
    const reading = voltage == null ? "No se recibió valor numérico" : `${voltage.toLocaleString("es", { maximumFractionDigits: 1 })} V`;
    detail = `${reading}${location ? ` · ${location}` : ""}`;
    inferredPriority = voltage === 0 ? "critical" : fluctuating ? "warning" : "system";
  } else if (["aforo", "occupancy"].includes(type) || event.occupancy != null) {
    const occupancy = event.occupancy ?? value;
    title = "Aforo actualizado";
    detail = `${readableLabel(occupancy)} personas${location ? ` · ${location}` : ""}`;
  } else if (type === "energy" || event.energy_kwh != null) {
    title = "Consumo actualizado";
    detail = `${readableLabel(event.energy_kwh ?? value)} kWh${location ? ` · ${location}` : ""}`;
  } else if (event.message) {
    title = readableLabel(type);
    detail = readableLabel(event.message);
  } else {
    title = readableLabel(type);
    const summary = event.valor == null ? "" : readableLabel(value);
    detail = [summary, location].filter(Boolean).join(" · ");
  }

  if (winner?.message && !detail.toLocaleLowerCase("es").includes(String(winner.message).toLocaleLowerCase("es"))) {
    detail = [detail, readableLabel(winner.message)].filter(Boolean).join(" · ");
  }

  return {
    title: capitalize(title),
    detail,
    priority: normalizePriority(priority || winner?.severity || inferredPriority),
    timestamp: timestamp || event.timestamp || data?.timestamp || new Date().toISOString(),
  };
}

function normalizePriority(value) {
  const priority = String(value || "system").toLowerCase();
  if (["normal", "success", "granted", "ok"].includes(priority)) return "success";
  if (["warning", "warn", "lockdown"].includes(priority)) return "warning";
  if (["critical", "error", "denied", "lockout"].includes(priority)) return "critical";
  return "system";
}

function readableValue(value) {
  if (value == null) return "";
  if (typeof value === "object") return readableValue(value.valor ?? value.value ?? value.lectura ?? value.count ?? value.personas);
  return String(value).trim();
}

function readableLabel(value) {
  if (value == null || value === "") return "";
  return String(value)
    .replace(/^CAM_\d+_/, "")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim();
}

function capitalize(value) {
  return value ? `${value[0].toLocaleUpperCase("es")}${value.slice(1)}` : "Actividad del modelo";
}

function titleCase(value) {
  return value.toLocaleLowerCase("es").replace(/(^|\s)\p{L}/gu, (letter) => letter.toLocaleUpperCase("es"));
}

function connectionMessage(value) {
  const status = String(value || "").toLowerCase();
  if (["authenticated", "connected", "model_connected"].includes(status)) return "Conectado al modelo";
  if (["disconnected", "model_disconnected"].includes(status)) return "Desconectado del modelo";
  if (["connecting", "waiting_signal"].includes(status)) return "Conectando con el modelo";
  return readableLabel(value || "Estado de conexión actualizado");
}
