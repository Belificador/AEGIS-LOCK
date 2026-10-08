import { mountHeader } from "./components/header/header.js";
import { mountCriticalAlert } from "./components/sidebar-right/critical-alert.js";
import { mountGlobalAlertBanner } from "./components/global-alert-banner.js";
import { mountSidebarLeft } from "./components/sidebar-left/sidebar-left.js";
import { mountSidebarRight } from "./components/sidebar-right/sidebar-right.js";
import { mountViewport } from "./components/viewport/viewport.js";
import { DataReceiver } from "./dataReceiver.js";
import { TelemetryEmitter } from "./eventEmitter.js";
import { mountAdminDiagnostics } from "./components/sidebar-right/admin-diagnostics.js";
import { createCameraModal } from "./components/viewport/camera-modal.js";
import { mountPanelExpansion } from "./components/panel-expansion.js";
import { mountSidebarResize } from "./components/sidebar-resize.js";
import { CAMERA_MARKERS } from "./components/viewport/camera-markers.js";
import { patchState, state } from "./store.js";
import { getVoltageReading } from "./voltage-reading.js";

const AUTH_URL = import.meta.env.VITE_AUTH_API_URL || "https://aegis-lock-api.onrender.com/api/login";
const API_ROOT = AUTH_URL.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");

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
  let adminDiagnostics = null;
  const header = mountHeader(document.querySelector("#header-root"), {
    user,
    onLogout,
    onOpenAdmin: () => adminDiagnostics?.open(),
  });
  if (user.role === "admin") adminDiagnostics = mountAdminDiagnostics({ session });
  const criticalAlerts = mountCriticalAlert({
    onAcknowledge: (incident, { hasPending }) => {
      void postAuditAction("ALARM_ACKNOWLEDGED", {
        event_id: incident.eventId,
        code: incident.code,
        zone: incident.zone,
        source: incident.source,
      });
      if (!hasPending) {
        viewport.clearIntrusionAlert();
        if (state.mode === "ALERTA") setMode("NORMAL", "ALERTA ATENDIDA");
      }
    },
  });
  const globalAlerts = mountGlobalAlertBanner();
  const sidebarLeft = mountSidebarLeft(document.querySelector("#sidebar-left-root"), { session, user });
  const viewport = mountViewport(document.querySelector("#viewport-root"), { onCameraSelected: openCamera });
  const right = mountSidebarRight(document.querySelector("#sidebar-right-root"), {
    role: user.role,
    onModeChange: setMode,
    onOpenCamera: openCamera,
    tacticalDockRoot: viewport.tacticalDock,
  });
  const cameraModal = createCameraModal({
    session,
    cameras: CAMERA_MARKERS,
    onAvailability: (cameraId, available) => right.setCameraAvailability(cameraId, available),
    onSelection: (camera, feedUrl) => right.updateCamera({
      tipo_evento: "camera_selected",
      valor: camera.id,
      zona: camera.location,
      metadata: { camera_id: camera.id, name: camera.shortName, location: camera.location, feed_url: feedUrl },
    }),
  });
  const cameraPublisher = session?.access_token && ["operator", "admin"].includes(user.role)
    ? new TelemetryEmitter({ accessToken: () => session.access_token })
    : null;
  cameraPublisher?.connect();
  const dashboard = document.querySelector("#dashboard-view");
  const root = dashboard;
  const panelExpansion = mountPanelExpansion();
  const sidebarResize = mountSidebarResize(dashboard.querySelector(".dashboard-grid"));
  const receiver = new DataReceiver({ url: wsUrl, onEvent: handleEvent, onLatency: (latency) => header.setLatency(latency), onStatus: (connection) => {
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
  if (right.initialMode.mode !== "NORMAL") setMode(right.initialMode.mode, right.initialMode.source, { audit: false });
  right.checkSchedule();
  const scheduleTimer = window.setInterval(() => right.checkSchedule(), 5000);

  function setMode(mode, source, { audit = true } = {}) {
    const previousMode = state.mode;
    patchState({ mode, modeSource: source });
    const label = mode === "LOCKDOWN" && source === "CIERRE PROGRAMADO" ? "CIERRE DE JORNADA" : mode;
    root.classList.remove("mode-lockdown", "mode-evacuacion", "mode-cierre", "mode-alerta");
    if (label === "LOCKDOWN") root.classList.add("mode-lockdown");
    if (label === "EVACUACIÓN") root.classList.add("mode-evacuacion");
    if (label === "CIERRE DE JORNADA") root.classList.add("mode-cierre");
    if (label === "ALERTA") root.classList.add("mode-alerta");
    header.setMode(mode, source);
    right.setMode(label);
    viewport.setMode(label);
    if (audit && mode !== previousMode) {
      if (mode === "LOCKDOWN") void postAuditAction("LOCKDOWN_ACTIVATED", { source });
      if (mode === "EVACUACIÓN") void postAuditAction("EVACUATION_ACTIVATED", { source });
      if (mode === "NORMAL" && previousMode === "LOCKDOWN") void postAuditAction("LOCKDOWN_RELEASED", { source });
      if (mode === "NORMAL" && previousMode === "EVACUACIÓN") void postAuditAction("EVACUATION_RELEASED", { source });
      if (["LOCKDOWN", "EVACUACIÓN", "NORMAL"].includes(mode)) {
        right.events.append({
          kind: "local_mode",
          mode: label,
          actor: user.role === "admin" ? "Administrador" : user.username,
          source,
        });
      }
    }
  }

  async function postAuditAction(action, details) {
    if (!session?.access_token) return;
    try {
      const response = await fetch(`${API_ROOT}/api/v1/audit`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action, details }),
      });
      if (!response.ok) console.warn(`No se pudo registrar ${action} en la auditoría AEGIS.`);
    } catch (error) {
      console.warn(`No se pudo registrar ${action} en la auditoría AEGIS:`, error.message);
    }
  }

  function publishCameraSelection(camera) {
    const event = {
      origen: "aegis-dashboard",
      tipo_evento: "camera_selected",
      zona: camera.zone,
      valor: camera.cameraId,
      timestamp: new Date().toISOString(),
      metadata: {
        camera_id: camera.cameraId,
        cameraId: camera.cameraId,
        name: camera.markerName || camera.label || camera.cameraId,
        location: camera.zone,
        node_name: camera.markerName,
      },
    };
    cameraPublisher?.send(event);
  }

  function openCamera(camera) {
    const cameraId = camera.cameraId || camera.id;
    const number = Number(/^CAM_(\d+)_/.exec(cameraId)?.[1]);
    const details = {
      id: cameraId,
      cameraId,
      numericId: Number.isFinite(number) ? number : null,
      shortName: camera.shortName || cameraId.replace(/^CAM_\d+_/, "").replaceAll("_", " "),
      location: camera.zone || camera.location || "Ubicación pendiente",
    };
    right.updateCamera({
      tipo_evento: "camera_selected",
      valor: cameraId,
      zona: details.location,
      metadata: { camera_id: cameraId, location: details.location },
    });
    void cameraModal.open(details);
    publishCameraSelection({ ...camera, cameraId, label: details.shortName });
  }

  function handleEvent(payload) {
    if (payload.kind === "connection") {
      right.events.append(payload, { priority: "system" });
      return;
    }
    if (payload.kind === "error") {
      right.events.append(payload, { priority: "critical" });
      return;
    }
    if (payload.kind === "message") {
      right.events.append(payload, { priority: "system" });
      return;
    }
    if (payload.kind !== "telemetry" || !payload.event) return;

    const event = payload.event;
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
    globalAlerts.ingest({ event, alerts });
    criticalAlerts.ingest({ event, alerts });
    sidebarLeft.update(event);
    viewport.update({ ...event, alerts });
    if (String(event.tipo_evento).toLowerCase() === "camera_selected" && event.origen !== "aegis-dashboard") right.updateCamera(event);
    patchState({ modelConnected: true, connection: "MODEL_CONNECTED", telemetry: { ...state.telemetry, ...event } });
    right.events.append(event, { alerts, timestamp: event.timestamp });
    for (const alert of alerts) {
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), alert.message] });
      if (state.mode === "NORMAL" && ["critical", "lockdown"].includes(alert.severity)) setMode("ALERTA", alert.code);
    }

    const deniedPin = String(event.tipo_evento).toLowerCase() === "acceso_pin" && String(event.valor).toUpperCase() === "DENIED";
    if (deniedPin) {
      const intrusion = `ACCESO DENEGADO${event.zona ? ` · ${event.zona}` : ""}${event.origen ? ` · ${event.origen}` : ""}`;
      viewport.setIntrusionAlert?.(event.zona);
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), intrusion] });
      if (state.mode === "NORMAL") setMode("ALERTA", "INTRUSIÓN DETECTADA");
    } else if (event.intrusion && !alerts.length && state.mode === "NORMAL") {
      setMode("ALERTA", "INTRUSIÓN DETECTADA");
    }
    if (getVoltageReading(event) === 0) {
      patchState({ recentAlerts: [...state.recentAlerts.slice(-9), "Apagón eléctrico detectado"] });
      if (state.mode === "NORMAL") setMode("ALERTA", "APAGÓN ELÉCTRICO");
    }
  }

  function destroy() {
    receiver.stop();
    cameraPublisher?.destroy();
    adminDiagnostics?.dispose();
    criticalAlerts.dispose();
    globalAlerts.dispose();
    cameraModal.dispose();
    panelExpansion.dispose();
    sidebarResize.destroy();
    viewport.destroy();
    right.destroy();
    sidebarLeft.destroy();
    header.destroy();
    document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
    window.clearInterval(scheduleTimer);
    dashboard.classList.remove("mode-lockdown", "mode-evacuacion", "mode-cierre", "mode-alerta");
  }

  return { destroy };
}
