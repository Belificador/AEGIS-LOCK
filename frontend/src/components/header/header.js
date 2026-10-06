export function mountHeader(root, { user, onLogout }) {
  root.className = "aegis-header";
  root.innerHTML = `
    <div class="header-brand"><div class="header-emblem" aria-hidden="true"><span>A</span></div><div><p class="eyebrow">AEGIS LOCK · CONTROL TÁCTICO</p><h1>CENTRAL DE MONITOREO - AEGIS LOCK</h1></div></div>
    <div class="header-middle"><div id="global-mode" class="system-state" data-mode="NO CONECTADO"><i class="status-led led-offline"></i><span>MODELO NO CONECTADO</span></div><div class="header-clock"><span>HORA LOCAL</span><time id="dashboard-clock">--:--:--</time></div></div>
    <div class="header-user"><div><label class="profile-label" for="profile-select">PERFIL DETECTADO</label><select id="profile-select" class="profile-select" disabled></select></div><span id="connection-state" class="header-connection"><i class="status-led led-offline"></i> MODELO NO CONECTADO</span><button id="logout-button" class="logout-button" type="button">CERRAR SESIÓN</button></div>`;

  const profile = root.querySelector("#profile-select");
  const option = document.createElement("option");
  option.value = user.role;
  const roleLabel = { admin: "ADMINISTRADOR", operator: "OPERADOR", viewer: "OBSERVADOR" }[user.role] || "PERFIL";
  option.textContent = `${roleLabel} · ${user.username}`;
  profile.append(option);
  root.querySelector("#logout-button").addEventListener("click", onLogout);

  const clock = root.querySelector("#dashboard-clock");
  const modeBadge = root.querySelector("#global-mode");
  let connected = false;
  let mode = "NORMAL";
  let source = "";
  const updateClock = () => { clock.textContent = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()); };
  updateClock();
  const clockTimer = window.setInterval(updateClock, 1000);

  return {
    setMode(nextMode, nextSource) {
      mode = nextMode;
      source = nextSource;
      renderMode();
    },
    setConnection(status) {
      const connection = root.querySelector("#connection-state");
      const led = connection.querySelector(".status-led");
      connected = status === "MODEL_CONNECTED";
      const labels = {
        MODEL_DISCONNECTED: "MODELO NO CONECTADO",
        CONNECTING: "CONECTANDO AL MODELO",
        WAITING_SIGNAL: "ESPERANDO SEÑAL",
        MODEL_CONNECTED: "🟢 CONECTADO A RENDER",
      };
      connection.lastChild.textContent = ` ${labels[status] || "🔴 DESCONECTADO"}`;
      led.className = `status-led ${connected ? "led-normal" : status === "CONNECTING" || status === "WAITING_SIGNAL" ? "led-warning" : "led-offline"}`;
      renderMode();
    },
    destroy() { window.clearInterval(clockTimer); },
  };

  function renderMode() {
    const display = mode === "LOCKDOWN" && source === "CIERRE PROGRAMADO" ? "CIERRE DE JORNADA" : mode;
    modeBadge.dataset.mode = connected ? display : "NO CONECTADO";
    modeBadge.querySelector("span").textContent = connected ? `ESTADO: ${display}` : "MODELO NO CONECTADO";
    const color = !connected ? "led-offline" : display === "NORMAL" ? "led-normal" : display === "ALERTA" ? "led-warning" : "led-critical";
    modeBadge.querySelector(".status-led").className = `status-led ${color}`;
  }
}
