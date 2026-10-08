export const VOLTAGE_NORMAL_MIN_V = 110;
export const VOLTAGE_NORMAL_MAX_V = 220;

export function parseVoltageReading(value) {
  if (value == null || typeof value === "boolean" || (typeof value === "string" && !value.trim())) return null;
  const voltage = Number(value);
  return Number.isFinite(voltage) ? voltage : null;
}

export function getVoltageReading(event = {}) {
  const explicit = parseVoltageReading(event.voltage_v);
  if (explicit != null) return explicit;

  const eventType = String(event.tipo_evento || event.event_type || "").trim().toLowerCase();
  if (!new Set(["voltaje", "voltage"]).has(eventType)) return null;

  const value = event.valor;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return parseVoltageReading(
      value.voltage_v ?? value.voltage ?? value.v ?? value.lectura ?? value.value ?? value.valor,
    );
  }
  return parseVoltageReading(value);
}
