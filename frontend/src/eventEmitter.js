const DEFAULT_TELEMETRY_WS_URL = import.meta.env.VITE_TELEMETRY_WS_URL
  || "wss://aegis-lock-api.onrender.com/ws/telemetry";

export class TelemetryEmitter {
  constructor({
    url = DEFAULT_TELEMETRY_WS_URL,
    accessToken = null,
  } = {}) {
    this.url = url;
    this.accessToken = accessToken;
    this.socket = null;
    this.connected = false;
    this.queue = [];
    this.retryTimer = null;
    this.retryAttempt = 0;
    this.stopped = true;
    this.statusListeners = new Set();
  }

  connect() {
    if (!this.url || this.stopped === false) return this.socket;
    this.stopped = false;
    return this._connect();
  }

  _connect() {
    if (this.socket && this.socket.readyState < WebSocket.CLOSING) return this.socket;
    this.socket = new WebSocket(this.url);
    const socket = this.socket;
    this._setStatus("CONNECTING");
    socket.addEventListener("open", () => {
      if (socket !== this.socket) return;
      const token = typeof this.accessToken === "function" ? this.accessToken() : this.accessToken;
      if (!token) {
        socket.close(4401, "Se requiere JWT para emitir telemetría");
        return;
      }
      socket.send(JSON.stringify({ type: "auth", token }));
    });
    socket.addEventListener("message", ({ data }) => {
      if (socket !== this.socket) return;
      let payload;
      try { payload = JSON.parse(data); } catch { return; }
      if (payload?.kind === "connection" && payload.status === "authenticated") {
        this.connected = true;
        this.retryAttempt = 0;
        this._setStatus("ONLINE");
        this._flush();
      }
    });
    socket.addEventListener("close", () => {
      if (socket !== this.socket) return;
      this.socket = null;
      this.connected = false;
      this._setStatus("OFFLINE");
      this._scheduleRetry();
    });
    socket.addEventListener("error", () => {
      if (socket === this.socket && socket.readyState !== WebSocket.CLOSED) socket.close();
    });
    return socket;
  }

  send(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("La telemetría debe ser un objeto JSON.");
    }
    if (this.connected && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
      return true;
    }
    if (this.queue.length === 20) this.queue.shift();
    this.queue.push(payload);
    this.connect();
    return false;
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

  _flush() {
    while (this.connected && this.socket?.readyState === WebSocket.OPEN && this.queue.length) {
      this.socket.send(JSON.stringify(this.queue.shift()));
    }
  }

  _scheduleRetry() {
    if (this.stopped || this.retryTimer !== null) return;
    const delay = Math.min(1000 * 2 ** this.retryAttempt, 30000);
    this.retryAttempt += 1;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this._connect();
    }, delay);
  }

  disconnect() {
    this.stopped = true;
    window.clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.connected = false;
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "Telemetry source stopped");
    this._setStatus("OFFLINE");
  }

  destroy() {
    this.disconnect();
    this.queue.length = 0;
    this.statusListeners.clear();
  }
}
