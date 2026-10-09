import { resolveLatestTelemetryUrl } from "./telemetry-api-url.js";
import { parseVoltageReading } from "./voltage-reading.js";

const VITE_ENV = import.meta.env || {};
const LATEST_URL = resolveLatestTelemetryUrl(VITE_ENV.VITE_AUTH_API_URL);
const POLL_INTERVAL_MS = 2000;
const REQUEST_TIMEOUT_MS = 8000;
const MAX_SEEN_EVENTS = 2048;

export class DataReceiver {
  constructor({ onEvent, onStatus, onLatency = () => {}, url = LATEST_URL, pollIntervalMs = POLL_INTERVAL_MS }) {
    this.onEvent = onEvent;
    this.onStatus = onStatus;
    this.onLatency = onLatency;
    this.url = url || LATEST_URL;
    this.pollIntervalMs = Math.max(500, Number(pollIntervalMs) || POLL_INTERVAL_MS);
    this.pollTimer = null;
    this.requestController = null;
    this.requestTimeout = null;
    this.polling = false;
    this.stopped = true;
    this.session = null;
    this.seenEvents = new Set();
    this.hasApiConnection = false;
    this.lastError = null;
  }

  start(session) {
    if (!this.stopped) return;
    this.session = session;
    this.stopped = false;
    this.onStatus("CONNECTING");
    void this.poll();
    this.pollTimer = window.setInterval(() => { void this.poll(); }, this.pollIntervalMs);
  }

  stop() {
    this.stopped = true;
    window.clearInterval(this.pollTimer);
    window.clearTimeout(this.requestTimeout);
    this.pollTimer = null;
    this.requestTimeout = null;
    this.requestController?.abort();
    this.requestController = null;
    this.polling = false;
    this.hasApiConnection = false;
    this.lastError = null;
    this.seenEvents.clear();
    this.onLatency(null);
    this.onStatus("MODEL_DISCONNECTED");
  }

  async poll() {
    if (this.stopped || this.polling) return;
    this.polling = true;
    const controller = new AbortController();
    this.requestController = controller;
    const startedAt = performance.now();
    this.requestTimeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(this.url, {
        method: "GET",
        headers: this.session?.access_token
          ? { Authorization: `Bearer ${this.session.access_token}`, Accept: "application/json" }
          : { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = typeof payload.detail === "string" ? payload.detail : `Error HTTP ${response.status}`;
        throw new Error(detail);
      }

      this.onLatency(performance.now() - startedAt);
      this.lastError = null;
      if (!this.hasApiConnection) {
        this.hasApiConnection = true;
        this.onEvent({ kind: "connection", status: "authenticated", transport: "http-poll" });
      }

      const events = Array.isArray(payload.events) ? payload.events : [];
      this.onStatus(events.length ? "MODEL_CONNECTED" : "WAITING_SIGNAL");
      for (const item of events) {
        const rawEvent = item?.event && typeof item.event === "object" ? item.event : item;
        if (!rawEvent || typeof rawEvent !== "object") continue;
        const dedupeKey = this.dedupeKey(rawEvent);
        if (dedupeKey && this.seenEvents.has(dedupeKey)) continue;
        if (dedupeKey) this.rememberEvent(dedupeKey);
        this.onEvent({
          kind: "telemetry",
          event: normalizeTelemetry(rawEvent),
          alerts: Array.isArray(item.alerts) ? item.alerts : [],
          raw: item,
        });
      }
    } catch (error) {
      if (this.stopped || controller.signal.aborted && this.requestController !== controller) return;
      this.onLatency(null);
      const message = error?.message || "No se pudo consultar la telemetría de AEGIS.";
      this.onStatus("MODEL_DISCONNECTED");
      if (message !== this.lastError) this.onEvent({ kind: "error", detail: message });
      this.lastError = message;
      this.hasApiConnection = false;
    } finally {
      window.clearTimeout(this.requestTimeout);
      this.requestTimeout = null;
      if (this.requestController === controller) this.requestController = null;
      this.polling = false;
    }
  }

  dedupeKey(event) {
    if (typeof event.event_id === "string" && event.event_id) return event.event_id;
    const type = event.tipo_evento || event.event_type || "telemetry";
    const zone = event.zone || event.zona || "GLOBAL";
    if (!event.timestamp) return null;
    return `${type}:${zone}:${event.timestamp}:${JSON.stringify(event.valor ?? null)}`;
  }

  rememberEvent(eventId) {
    this.seenEvents.add(eventId);
    if (this.seenEvents.size > MAX_SEEN_EVENTS) {
      this.seenEvents.delete(this.seenEvents.values().next().value);
    }
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
  if (type === "aforo" || type === "occupancy") {
    const actionEvent = metadata.estado_actual === false
      || ["accion", "motivo", "enviados", "withdrawals"].some((field) => metadata[field] != null);
    const occupancy = value == null || value === "" ? null : Number(value);
    if (actionEvent || occupancy == null || !Number.isFinite(occupancy)) delete event.occupancy;
    else event.occupancy = occupancy;
  }
  if (["iluminacion", "illumination", "lighting"].includes(type)) {
    const percent = value == null || value === "" ? null : Number(value);
    const factorPercent = metadata.factor_electrico == null ? null : Number(metadata.factor_electrico) * 100;
    if (percent != null && Number.isFinite(percent)) event.illumination_percent = percent;
    else if (factorPercent != null && Number.isFinite(factorPercent)) event.illumination_percent = factorPercent;
  }
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
