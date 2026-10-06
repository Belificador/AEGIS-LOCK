import { createMetricCard } from "./metric-card.js";

export function mountEnergyMetric(root) {
  const metric = createMetricCard(root, {
    title: "Consumo eléctrico",
    unit: "kW",
    className: "metric-card-energy",
    symbol: "ϟ",
    color: "#42d9ff",
    visual: "area",
    historyKey: "aegis.telemetry.energy.v1",
    digits: 2,
    statusText: "MODELO NO CONECTADO",
  });
  return {
    update(event) {
      const voltage = event.voltage_v;
      const wattsValue = event.power_kw == null ? event.metadata?.power_w ?? event.metadata?.watts : Number(event.power_kw) * 1000;
      if (voltage != null) metric.element.classList.toggle("is-critical", Number(voltage) === 0);
      if (event.power_kw != null) {
        const voltageLabel = voltage == null ? "— V" : `${voltage} V`;
        metric.set(event.power_kw, `${voltageLabel} · ${Math.round(wattsValue)} W`, event.timestamp, "kW");
        if (voltage != null) metric.element.querySelector(".metric-card-meta .status-led").className = `status-led ${Number(voltage) === 0 ? "led-critical" : "led-normal"}`;
      } else if (voltage != null) {
        const volts = Number(voltage);
        const watts = wattsValue == null ? "—" : `${Math.round(Number(wattsValue))}`;
        metric.set(volts, `${watts} W · ${volts === 0 ? "APAGÓN DETECTADO" : "ALIMENTACIÓN ACTIVA"}`, event.timestamp, "V");
        metric.element.querySelector(".metric-card-meta .status-led").className = `status-led ${volts === 0 ? "led-critical" : "led-normal"}`;
      }
    },
    setConnection(connected) {
      metric.setStatus(connected ? "ESPERANDO LECTURA ELÉCTRICA" : "MODELO NO CONECTADO", connected);
    },
  };
}
