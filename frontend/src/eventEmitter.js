import { resolveLatestTelemetryUrl } from "./telemetry-api-url.js";

const VITE_ENV = import.meta.env || {};
const DEFAULT_POST_URL = resolveLatestTelemetryUrl(VITE_ENV.VITE_AUTH_API_URL).replace(/\/latest$/, "");

/** REST publisher for authenticated dashboard events such as camera selection. */
export class TelemetryEmitter {
  constructor({ url = DEFAULT_POST_URL, accessToken = null } = {}) {
    this.url = url;
    this.accessToken = accessToken;
    this.connected = false;
    this.queue = [];
    this.retryTimer = null;
    this.retryAttempt = 0;
    this.stopped = true;
    this.sending = false;
    this.requestController = null;
    this.statusListeners = new Set();
  }

  connect() {
    if (!this.url || !this.stopped) return;
    this.stopped = false;
    this.connected = Boolean(this.getAccessToken());
    this._setStatus(this.connected ? "ONLINE" : "OFFLINE");
    if (this.queue.length && this.connected) void this._flush();
  }

  send(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("La telemetría debe ser un objeto JSON.");
    }
    if (this.stopped) this.connect();
    if (this.queue.length >= 20) this.queue.shift();
    this.queue.push(payload);
    this.connected = Boolean(this.getAccessToken());
    if (this.connected) void this._flush();
    return this.connected;
  }

  async _flush() {
    if (this.sending || this.stopped || !this.queue.length) return;

    this.sending = true;
    try {
      while (this.queue.length && !this.stopped) {
        const token = this.getAccessToken();
        if (!token) throw new Error("La sesión AEGIS expiró; inicia sesión nuevamente.");
        const controller = new AbortController();
        this.requestController = controller;
        const response = await fetch(this.url, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify(this.queue[0]),
          signal: controller.signal,
        });
        const payload = await response.json().catch(() => ({}));
        this.requestController = null;
        if (!response.ok || payload.accepted !== true) {
          const detail = typeof payload.detail === "string" ? payload.detail : `AEGIS respondió HTTP ${response.status}`;
          if (response.status >= 500 || response.status === 429) throw new Error(detail);
          this.queue.shift();
          this.connected = false;
          this._setStatus("DEGRADED");
          console.error("[TelemetryEmitter] AEGIS REST rechazó la selección:", detail);
          continue;
        }
        this.queue.shift();
        this.connected = true;
        this.retryAttempt = 0;
        this._setStatus("ONLINE");
      }
    } catch (error) {
      if (!this.stopped) {
        this.connected = false;
        this._setStatus("OFFLINE");
        console.error("[TelemetryEmitter] AEGIS REST:", error.message);
        this._scheduleRetry();
      }
    } finally {
      this.requestController = null;
      this.sending = false;
    }
  }

  onStatus(callback) {
    if (typeof callback !== "function") return () => {};
    this.statusListeners.add(callback);
    return () => this.statusListeners.delete(callback);
  }

  _setStatus(status) {
    for (const callback of this.statusListeners) {
      try { callback(status); } catch (error) { console.error("[TelemetryEmitter] status listener:", error); }
    }
  }

  _scheduleRetry() {
    if (this.stopped || this.retryTimer !== null) return;
    const delay = Math.min(1000 * 2 ** this.retryAttempt, 30000);
    this.retryAttempt += 1;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this.connected = Boolean(this.getAccessToken());
      if (this.connected) this._setStatus("ONLINE");
      void this._flush();
    }, delay);
  }

  disconnect() {
    this.stopped = true;
    window.clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.connected = false;
    this.requestController?.abort();
    this.requestController = null;
    this._setStatus("OFFLINE");
  }

  destroy() {
    this.disconnect();
    this.queue.length = 0;
    this.statusListeners.clear();
  }
}
