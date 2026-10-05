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
      if (event.power_kw != null) {
        const watts = Number(event.power_kw) * 1000;
        const voltage = event.voltage_v == null ? "—" : `${event.voltage_v} V`;
        metric.set(event.power_kw, `${voltage} · ${Math.round(watts)} W`, event.timestamp, "kW");
      } else if (event.voltage_v != null && metric.value == null) {
        metric.setStatus(`VOLTAJE RECIBIDO · ${event.voltage_v} V`, true);
      }
    },
    setConnection(connected) {
      metric.setStatus(connected ? "ESPERANDO LECTURA ELÉCTRICA" : "MODELO NO CONECTADO", connected);
    },
  };
}
