import { getVoltageReading, VOLTAGE_NORMAL_MAX_V, VOLTAGE_NORMAL_MIN_V } from "../voltage-reading.js";

export function mountGlobalAlertBanner() {
  const root = document.createElement("section");
  root.className = "global-alert-banners";
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "assertive");
  root.setAttribute("aria-label", "Alertas activas del edificio");
  document.body.append(root);
  let active = new Map();

  function ingest(payload) {
    const next = reduceGlobalAlerts(active, payload);
    if (sameAlerts(active, next)) return;
    active = next;
    render();
  }

  function render() {
    root.replaceChildren();
    for (const alert of active.values()) {
      const banner = document.createElement("article");
      banner.className = `global-alert-banner is-${alert.severity}`;
      const status = document.createElement("span");
      status.className = "global-alert-status";
      status.textContent = "ALERTA ACTIVA";
      const content = document.createElement("div");
      content.className = "global-alert-content";
      const title = document.createElement("strong");
      title.textContent = alert.title;
      const detail = document.createElement("span");
      detail.textContent = `${alert.message} · ${alert.zone}`;
      content.append(title, detail);
      banner.append(status, content);
      root.append(banner);
    }
    root.hidden = active.size === 0;
  }

  return {
    ingest,
    dispose() { root.remove(); active.clear(); },
  };
}

export function reduceGlobalAlerts(previous, payload) {
  const active = new Map(previous);
  const event = payload?.event || payload || {};
  const alerts = Array.isArray(payload?.alerts) ? payload.alerts : Array.isArray(event.alerts) ? event.alerts : [];
  const source = String(event.source_id || event.origen || "aegis");
  const zone = String(event.zone || event.zona || "GLOBAL");
  const stateKey = `${source}:${zone}`;
  const type = String(event.tipo_evento || event.event_type || "").toLowerCase();
  const value = String(event.valor ?? "").trim().toUpperCase();
  const voltage = getVoltageReading(event);

  if (voltage === 0 || alerts.some((alert) => alert?.code === "POWER_LOSS")) {
    active.set(`POWER_LOSS:${stateKey}`, {
      title: "PÉRDIDA DE ENERGÍA",
      message: findAlertMessage(alerts, "POWER_LOSS") || "Se detectó una lectura de 0 V.",
      severity: "critical",
      zone,
    });
  } else if (voltage != null && voltage > 0) {
    active.delete(`POWER_LOSS:${stateKey}`);
  }

  const fluctuationAlert = alerts.find((alert) => alert?.code === "VOLTAGE_FLUCTUATION");
  if (fluctuationAlert || (voltage != null && voltage > 0 && (voltage < VOLTAGE_NORMAL_MIN_V || voltage > VOLTAGE_NORMAL_MAX_V))) {
    active.set(`VOLTAGE_FLUCTUATION:${stateKey}`, {
      title: "FLUCTUACIÓN DE VOLTAJE",
      message: "La lectura está fuera del rango normal (110–220 V).",
      severity: "warning",
      zone,
    });
  } else if (voltage != null && voltage >= VOLTAGE_NORMAL_MIN_V && voltage <= VOLTAGE_NORMAL_MAX_V) {
    active.delete(`VOLTAGE_FLUCTUATION:${stateKey}`);
  }

  const accessEvent = ["acceso_pin", "access_pin"].includes(type);
  const denied = accessEvent && ["DENIED", "LOCKOUT"].includes(value);
  const intrusion = event.intrusion === true || alerts.some((alert) => alert?.code === "INTRUSION");
  if (denied || intrusion) {
    active.set(`ACCESS_DENIED:${stateKey}`, {
      title: denied ? "ACCESO DENEGADO" : "INTRUSIÓN DETECTADA",
      message: denied
        ? value === "LOCKOUT" ? "Bloqueo por intentos de acceso fallidos." : "Se rechazó un intento de acceso."
        : "Se detectó actividad de intrusión.",
      severity: "critical",
      zone,
    });
  } else if (accessEvent && ["GRANTED", "NORMAL", "CLEAR"].includes(value)) {
    active.delete(`ACCESS_DENIED:${stateKey}`);
  } else if (event.intrusion === false) {
    active.delete(`ACCESS_DENIED:${stateKey}`);
  }

  return active;
}

function findAlertMessage(alerts, code) {
  return alerts.find((alert) => alert?.code === code)?.message || "";
}

function sameAlerts(left, right) {
  if (left.size !== right.size) return false;
  for (const [key, alert] of left) {
    const next = right.get(key);
    if (!next || alert.title !== next.title || alert.message !== next.message || alert.zone !== next.zone || alert.severity !== next.severity) {
      return false;
    }
  }
  return true;
}
