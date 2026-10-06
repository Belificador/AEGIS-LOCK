export function classifyTemperature(event = {}) {
  const temperature = Number(event.temperature_c ?? event.valor);
  const directionValue = event.metadata?.direccion;
  const direction = Number(directionValue);
  const outsideComfort = directionValue != null && Number.isFinite(direction)
    ? direction !== 0
    : temperature < 22 || temperature > 26;
  const critical = temperature > 38;
  const warning = Number.isFinite(temperature) && outsideComfort && !critical;
  const description = critical
    ? "ALERTA · TEMPERATURA CRÍTICA"
    : warning
      ? `FUERA DE CONFORT · ${temperature > 26 ? "ALTA" : "BAJA"}`
      : "TEMPERATURA NORMAL";
  return { warning, critical, description };
}
