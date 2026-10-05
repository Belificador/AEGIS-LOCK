const WS_URL = import.meta.env.VITE_WS_URL || "";

export class DataReceiver {
  constructor({ onEvent, onStatus }) {
    this.onEvent = onEvent;
    this.onStatus = onStatus;
    this.socket = null;
    this.reconnectTimer = null;
    this.stopped = true;
    this.reconnectDelay = 800;
    this.session = null;
  }

  start(session) {
    this.session = session;
    this.stopped = false;
    if (WS_URL && session?.access_token) this.connect();
    else this.onStatus("MODEL_DISCONNECTED");
  }

  stop() {
    this.stopped = true;
    window.clearTimeout(this.reconnectTimer);
    this.socket?.close(1000, "Session ended");
    this.socket = null;
  }

  connect() {
    if (this.stopped) return;
    this.onStatus("CONNECTING");
    try {
      this.socket = new WebSocket(WS_URL);
    } catch {
      this.scheduleReconnect();
      return;
    }
    const socket = this.socket;
    socket.addEventListener("open", () => {
      socket.send(JSON.stringify({ type: "auth", token: this.session.access_token }));
    });
    socket.addEventListener("message", ({ data }) => {
      try {
        const payload = JSON.parse(data);
        if (payload.kind === "connection") {
          this.reconnectDelay = 800;
          this.onStatus("WAITING_SIGNAL");
        }
        if (payload.kind === "telemetry" && payload.event) {
          this.onStatus("MODEL_CONNECTED");
        }
        this.onEvent(payload);
      } catch {
        this.onEvent({ kind: "error", detail: "Evento JSON recibido con formato inválido." });
      }
    });
    socket.addEventListener("close", () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (!this.stopped) {
        this.onStatus("MODEL_DISCONNECTED");
        this.scheduleReconnect();
      }
    });
    socket.addEventListener("error", () => this.onStatus("MODEL_DISCONNECTED"));
  }

  scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    const delay = this.reconnectDelay;
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}
