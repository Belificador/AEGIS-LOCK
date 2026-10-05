import { createMetricCard } from "./metric-card.js";

export function mountTemperatureMetric(root) {
  const metric = createMetricCard(root, {
    title: "Temperatura promedio",
    unit: "°C",
    className: "metric-card-temperature",
    symbol: "⌁",
    color: "#ff754f",
    visual: "area",
    historyKey: "aegis.telemetry.temperature.v1",
    digits: 1,
    statusText: "MODELO NO CONECTADO",
  });
  return {
    update(event) {
      if (event.temperature_c == null) return;
      const temperature = Number(event.temperature_c);
      metric.element.classList.toggle("is-critical", temperature > 38);
      metric.element.classList.toggle("is-warning", temperature > 30 && temperature <= 38);
      metric.set(temperature, "LECTURA RECIBIDA DEL MODELO", event.timestamp, "°C");
    },
    setConnection(connected) {
      metric.setStatus(connected ? "ESPERANDO LECTURA DE TEMPERATURA" : "MODELO NO CONECTADO", connected);
      if (!connected) metric.element.classList.remove("is-critical", "is-warning");
    },
  };
}
