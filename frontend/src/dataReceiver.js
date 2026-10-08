import { parseVoltageReading } from "./voltage-reading.js";
import { resolveDashboardWebSocketUrl } from "./dashboard-websocket-url.js";

const WS_URL = import.meta.env.VITE_WS_URL;
const RECONNECT_DELAY_MS = 5000;

export class DataReceiver {
  constructor({ onEvent, onStatus, onLatency = () => {}, url = WS_URL }) {
    this.onEvent = onEvent;
    this.onStatus = onStatus;
    this.onLatency = onLatency;
    this.socket = null;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.pendingPing = null;
    this.pingSequence = 0;
    this.stopped = true;
    this.session = null;
    this.url = resolveDashboardWebSocketUrl(url || WS_URL, import.meta.env.VITE_AUTH_API_URL);
  }

  start(session) {
    this.session = session;
    this.stopped = false;
    this.connect();
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.heartbeatTimer);
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.pendingPing = null;
    this.onLatency(null);
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "Session ended");
  }

  connect() {
    if (this.stopped || this.socket) return;
    this.onStatus("CONNECTING");

    try {
      this.socket = new WebSocket(this.url);
    } catch (error) {
      this.onStatus("MODEL_DISCONNECTED");
      this.onEvent({ kind: "error", detail: error.message || "No se pudo abrir el WebSocket." });
      this.scheduleReconnect();
      return;
    }

    const socket = this.socket;
    socket.addEventListener("open", () => {
      if (socket !== this.socket) return;
      if (this.session?.access_token) {
        socket.send(JSON.stringify({ type: "auth", token: this.session.access_token }));
      }
      this.onStatus("MODEL_CONNECTED");
    });

    socket.addEventListener("message", ({ data }) => {
      if (socket !== this.socket) return;
      let payload;
      try {
        payload = JSON.parse(data);
      } catch {
        this.onEvent({ kind: "error", detail: "El emisor envió un mensaje que no es JSON válido.", raw: data });
        return;
      }

      if (payload?.kind === "connection") {
        this.onStatus("MODEL_CONNECTED");
        this.startHeartbeat(socket);
        this.onEvent(payload);
        return;
      }

      if (payload?.kind === "heartbeat" && payload.type === "pong") {
        if (this.pendingPing?.id === payload.id) {
          this.onLatency(performance.now() - this.pendingPing.startedAt);
          this.pendingPing = null;
        }
        return;
      }

      if (payload?.kind === "telemetry" && payload.event) {
        this.onStatus("MODEL_CONNECTED");
        this.onEvent({
          kind: "telemetry",
          event: normalizeTelemetry(payload.event),
          alerts: Array.isArray(payload.alerts) ? payload.alerts : [],
          raw: payload,
        });
        return;
      }

      if (payload?.tipo_evento || payload?.kind === "event") {
        this.onStatus("MODEL_CONNECTED");
        this.onEvent({ kind: "telemetry", event: normalizeTelemetry(payload), alerts: [], raw: payload });
        return;
      }

      if (payload?.kind === "error") {
        this.onEvent(payload);
        return;
      }

      // Algunos emisores envuelven el esquema del evento en `event` sin kind.
      if (payload?.event?.tipo_evento) {
        this.onStatus("MODEL_CONNECTED");
        this.onEvent({ kind: "telemetry", event: normalizeTelemetry(payload.event), alerts: [], raw: payload });
        return;
      }
      this.onEvent({ kind: "message", raw: payload });
    });

    socket.addEventListener("close", () => {
      if (this.socket !== socket) return;
      this.socket = null;
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
      this.pendingPing = null;
      this.onLatency(null);
      if (!this.stopped) {
        this.onStatus("MODEL_DISCONNECTED");
        this.scheduleReconnect();
      }
    });

    socket.addEventListener("error", () => {
      if (socket !== this.socket) return;
      this.onStatus("MODEL_DISCONNECTED");
      // `close` schedules the retry in browsers after the failed handshake/socket.
      if (socket.readyState !== WebSocket.CLOSED) socket.close();
    });
  }

  scheduleReconnect() {
    if (this.stopped || this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY_MS);
  }

  startHeartbeat(socket) {
    window.clearInterval(this.heartbeatTimer);
    this.pendingPing = null;
    this.heartbeatTimer = window.setInterval(() => {
      if (this.stopped || socket !== this.socket || socket.readyState !== WebSocket.OPEN) return;
      if (this.pendingPing && performance.now() - this.pendingPing.startedAt < 10_000) return;
      const id = `${Date.now()}-${++this.pingSequence}`;
      const startedAt = performance.now();
      this.pendingPing = { id, startedAt };
      try {
        socket.send(JSON.stringify({ type: "ping", id }));
      } catch {
        this.pendingPing = null;
      }
    }, 5000);
  }
}

export function normalizeTelemetry(input = {}) {
  const event = { ...input };
  const type = String(input.tipo_evento || input.event_type || "").trim().toLowerCase();
  const value = input.valor && typeof input.valor === "object"
    ? input.valor.valor ?? input.valor.value ?? input.valor.lectura ?? input.valor.celsius ?? input.valor.temperature_c ?? input.valor.count ?? input.valor.personas ?? input.valor
    : input.valor;
  const metadata = input.metadata && typeof input.metadata === "object" ? input.metadata : {};

  if (type === "temperatura" || type === "temperature") event.temperature_c = Number(value);
  if (type === "aforo" || type === "occupancy") event.occupancy = Number(value);
  if (type === "voltaje" || type === "voltage") {
    const objectValue = input.valor && typeof input.valor === "object" ? input.valor : {};
    const voltage = objectValue.voltage_v ?? objectValue.voltage ?? objectValue.v ?? input.voltage_v ?? value;
    const watts = objectValue.power_w ?? objectValue.watts ?? objectValue.w ?? metadata.power_w ?? metadata.watts;
    event.voltage_v = parseVoltageReading(voltage);
    if (watts != null && Number.isFinite(Number(watts))) event.power_kw = Number(watts) / 1000;
    else if (objectValue.power_kw != null || metadata.power_kw != null) event.power_kw = Number(objectValue.power_kw ?? metadata.power_kw);
  }

  event.source_id ??= input.origen;
  event.zone ??= input.zona;
  event.timestamp ??= input.timestamp;
  event.metadata = metadata;
  return event;
}
