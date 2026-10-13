import { mountChat } from "./chat/chat.js";
import { mountEnergyMetric } from "./metrics/energy.js";
import { mountOccupancyMetric } from "./metrics/occupancy.js";
import { mountTemperatureMetric } from "./metrics/temperature.js";

export function mountSidebarLeft(root, { session, role } = {}) {
  root.innerHTML = `
    <div class="sidebar-title"><div><span class="sidebar-kicker">TELEMETRY / LIVE FEED</span><h2>Señales del modelo</h2></div><span class="signal-status"><i class="status-led led-offline"></i><b id="signal-status">MODELO NO CONECTADO</b></span></div>
    <div id="sidebar-left-carousel" class="sidebar-left-carousel" role="region" tabindex="0" aria-label="Tarjetas de métricas y perfil. Desliza horizontalmente para ver más paneles.">
      <div id="metrics-stack" class="metrics-stack"></div>
      ${role === "admin"
        ? '<div id="sidebar-chat-root" class="sidebar-chat-root"></div>'
        : '<section class="operator-view-note" aria-label="Modo Operador de solo lectura"><strong>MODO OPERADOR · SOLO LECTURA</strong><p>Visualización del sistema y acceso a cámaras. El asistente Argus y los controles están reservados al Administrador.</p></section>'}
    </div>`;
  const stack = root.querySelector("#metrics-stack");
  const energy = mountEnergyMetric(stack);
  const occupancy = mountOccupancyMetric(stack);
  const temperature = mountTemperatureMetric(stack);
  if (role === "admin") mountChat(root.querySelector("#sidebar-chat-root"), session);
  return {
    update(event) {
      energy.update(event);
      occupancy.update(event);
      temperature.update(event);
    },
    setConnection(connected) {
      root.querySelector("#signal-status").textContent = connected ? "SEÑAL RECIBIDA" : "MODELO NO CONECTADO";
      root.querySelector(".signal-status .status-led").className = `status-led ${connected ? "led-normal" : "led-offline"}`;
      energy.setConnection(connected);
      occupancy.setConnection(connected);
      temperature.setConnection(connected);
    },
  };
}
