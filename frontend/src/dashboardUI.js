import { mountHeader } from "./components/header/header.js";
import { mountSidebarLeft } from "./components/sidebar-left/sidebar-left.js";
import { mountSidebarRight } from "./components/sidebar-right/sidebar-right.js";
import { mountViewport } from "./components/viewport/viewport.js";
import { DataReceiver } from "./dataReceiver.js";
import { patchState, state } from "./store.js";

export function mountDashboard({ user, session, onLogout }) {
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
  const receiver = new DataReceiver({ onEvent: handleEvent, onStatus: (connection) => {
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
      right.events.append({ kind: "connection", status: "authenticated" }, "system");
      return;
    }
    if (payload.kind === "error") {
      right.events.append(payload, "warning");
      return;
    }
    if (payload.kind !== "telemetry" || !payload.event) return;

    const event = payload.event;
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
    sidebarLeft.update(event);
    viewport.update(event);
    patchState({ modelConnected: true, connection: "MODEL_CONNECTED", telemetry: { ...state.telemetry, ...event } });
    right.events.append({ type: "telemetry", event }, alerts.length ? "warning" : "normal");
    for (const alert of alerts) {
      right.events.alert(`${alert.code}: ${alert.message}`, alert.severity === "critical" ? "critical" : "warning");
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), alert.message] });
      if (state.mode === "NORMAL") setMode("ALERTA", alert.code);
    }
    if (event.intrusion && !alerts.length && state.mode === "NORMAL") setMode("ALERTA", "INTRUSIÓN DETECTADA");
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
    header.destroy();
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    window.clearInterval(scheduleTimer);
    dashboard.classList.remove("mode-lockdown", "mode-evacuacion", "mode-cierre", "mode-alerta");
  }

  return { destroy };
}
