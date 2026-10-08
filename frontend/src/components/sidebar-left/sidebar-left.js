import { mountChat } from "./chat/chat.js";
import { mountEnergyMetric } from "./metrics/energy.js";
import { mountOccupancyMetric } from "./metrics/occupancy.js";
import { mountTemperatureMetric } from "./metrics/temperature.js";

export function mountSidebarLeft(root, { session, user } = {}) {
  root.innerHTML = `
    <div class="sidebar-title"><div><span class="sidebar-kicker">TELEMETRY / LIVE FEED</span><h2>Señales del modelo</h2></div><span class="signal-status"><i class="status-led led-offline"></i><b id="signal-status">MODELO NO CONECTADO</b></span></div>
    <div id="metrics-stack" class="metrics-stack"></div>
    <div id="sidebar-chat-root" class="sidebar-chat-root"></div>`;
  const stack = root.querySelector("#metrics-stack");
  const energy = mountEnergyMetric(stack);
  const occupancy = mountOccupancyMetric(stack);
  const temperature = mountTemperatureMetric(stack);
  const chat = mountChat(root.querySelector("#sidebar-chat-root"), session, user);
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
    destroy() { chat.destroy(); },
  };
}
