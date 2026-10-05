import { createMetricCard } from "./metric-card.js";

export function mountOccupancyMetric(root) {
  const metric = createMetricCard(root, {
    title: "Aforo en edificio",
    unit: "personas",
    className: "metric-card-occupancy",
    symbol: "⌂",
    color: "#42d9ff",
    visual: "occupancy",
    historyKey: "aegis.telemetry.occupancy.v1",
    digits: 0,
    statusText: "MODELO NO CONECTADO",
  });
  return {
    update(event) {
      if (event.occupancy != null) metric.set(event.occupancy, "LECTURA RECIBIDA DEL MODELO", event.timestamp, "personas");
    },
    setConnection(connected) {
      metric.setStatus(connected ? "ESPERANDO LECTURA DE AFORO" : "MODELO NO CONECTADO", connected);
    },
  };
}
