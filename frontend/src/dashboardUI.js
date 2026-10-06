import { mountHeader } from "./components/header/header.js";
import { mountSidebarLeft } from "./components/sidebar-left/sidebar-left.js";
import { mountSidebarRight } from "./components/sidebar-right/sidebar-right.js";
import { mountViewport } from "./components/viewport/viewport.js";
import { DataReceiver } from "./dataReceiver.js";
import { patchState, state } from "./store.js";

export function mountDashboard({ user, session, onLogout, wsUrl }) {
  patchState({
    user,
    mode: "NORMAL",
    modeSource: "",
    connection: "MODEL_DISCONNECTED",
    modelConnected: false,
    telemetry: { energy_kwh: null, power_kw: null, voltage_v: null, occupancy: null, temperature_c: null },
    recentAlerts: [],
  });
  const header = mountHeader(document.querySelector("#header-root"), { user, onLogout });
  const sidebarLeft = mountSidebarLeft(document.querySelector("#sidebar-left-root"), getAssistantContext);
  const right = mountSidebarRight(document.querySelector("#sidebar-right-root"), { role: user.role, onModeChange: setMode });
  const viewport = mountViewport(document.querySelector("#viewport-root"));
  const dashboard = document.querySelector("#dashboard-view");
  const root = dashboard;
  const voltageReadings = new Map();
  const receiver = new DataReceiver({ url: wsUrl, onEvent: handleEvent, onStatus: (connection) => {
    const modelConnected = connection === "MODEL_CONNECTED";
    patchState({ connection, modelConnected });
    header.setConnection(connection);
    sidebarLeft.setConnection(modelConnected);
    viewport.setConnection(modelConnected);
    right.setConnection(modelConnected);
  } });

  document.querySelectorAll("[data-close-dialog='history-dialog']").forEach((button) => {
    button.onclick = () => document.querySelector("#history-dialog").close();
  });
  receiver.start(session);
  if (right.initialMode.mode !== "NORMAL") setMode(right.initialMode.mode, right.initialMode.source);
  right.checkSchedule();
  const scheduleTimer = window.setInterval(() => right.checkSchedule(), 5000);

  function setMode(mode, source) {
    patchState({ mode, modeSource: source });
    const label = mode === "LOCKDOWN" && source === "CIERRE PROGRAMADO" ? "CIERRE DE JORNADA" : mode;
    root.classList.remove("mode-lockdown", "mode-evacuacion", "mode-cierre", "mode-alerta");
    if (label === "LOCKDOWN") root.classList.add("mode-lockdown");
    if (label === "EVACUACIÓN") root.classList.add("mode-evacuacion");
    if (label === "CIERRE DE JORNADA") root.classList.add("mode-cierre");
    if (label === "ALERTA") root.classList.add("mode-alerta");
    header.setMode(mode, source);
    right.setMode(label);
  }

  function handleEvent(payload) {
    if (payload.kind === "connection") {
      right.events.append(payload, "system");
      return;
    }
    if (payload.kind === "error") {
      right.events.append(payload.raw ?? payload, "warning");
      return;
    }
    if (payload.kind === "message") {
      right.events.append(payload.raw);
      return;
    }
    if (payload.kind !== "telemetry" || !payload.event) return;

    const event = payload.event;
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
    const voltageZone = event.zone || event.zona || "GLOBAL";
    const priorVoltage = voltageReadings.get(voltageZone);
    sidebarLeft.update(event);
    viewport.update(event);
    if (String(event.tipo_evento).toLowerCase() === "camera_selected") right.updateCamera(event);
    patchState({ modelConnected: true, connection: "MODEL_CONNECTED", telemetry: { ...state.telemetry, ...event } });
    right.events.append(payload.raw ?? event, alerts.length ? "warning" : "normal", event.timestamp);
    for (const alert of alerts) {
      right.events.alert(`${alert.code}: ${alert.message}`, alert.severity === "critical" ? "critical" : "warning");
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), alert.message] });
      if (state.mode === "NORMAL") setMode("ALERTA", alert.code);
    }

    const deniedPin = String(event.tipo_evento).toLowerCase() === "acceso_pin" && String(event.valor).toUpperCase() === "DENIED";
    if (deniedPin) {
      const intrusion = `ACCESO DENEGADO${event.zona ? ` · ${event.zona}` : ""}${event.origen ? ` · ${event.origen}` : ""}`;
      right.events.alert(intrusion, "critical");
      viewport.setIntrusionAlert?.(event.zona);
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), intrusion] });
      if (state.mode === "NORMAL") setMode("ALERTA", "INTRUSIÓN DETECTADA");
    } else if (event.intrusion && !alerts.length && state.mode === "NORMAL") {
      setMode("ALERTA", "INTRUSIÓN DETECTADA");
    }
    const currentVoltage = Number(event.voltage_v);
    if (event.voltage_v != null && Number.isFinite(currentVoltage)) voltageReadings.set(voltageZone, currentVoltage);
    if (event.voltage_v != null && Number.isFinite(currentVoltage) && priorVoltage != null && currentVoltage > 0 && currentVoltage < Number(priorVoltage)) {
      const drop = `CAÍDA DE VOLTAJE · ${priorVoltage} V → ${currentVoltage} V${event.zone || event.zona ? ` · ${event.zone || event.zona}` : ""}`;
      right.events.alert(drop, "warning");
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), drop] });
      if (state.mode === "NORMAL") setMode("ALERTA", "CAÍDA DE VOLTAJE");
    }
    if (event.voltage_v != null && currentVoltage === 0) {
      right.events.alert(`APAGÓN DETECTADO · ${event.zone || event.zona || "ALIMENTACIÓN GLOBAL"}`, "critical");
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), "Apagón eléctrico detectado"] });
      if (state.mode === "NORMAL") setMode("ALERTA", "APAGÓN ELÉCTRICO");
    }
  }

  function getAssistantContext() {
    return {
      modelConnected: state.modelConnected,
      mode: state.mode,
      telemetry: state.telemetry,
      recentAlerts: state.recentAlerts,
    };
  }

  function destroy() {
    receiver.stop();
    viewport.destroy();
    header.destroy();
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    window.clearInterval(scheduleTimer);
    dashboard.classList.remove("mode-lockdown", "mode-evacuacion", "mode-cierre", "mode-alerta");
  }

  return { destroy };
}
