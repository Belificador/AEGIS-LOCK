export function classifyPowerLossTransition(previousVoltage, currentVoltage) {
  const current = toFiniteVoltage(currentVoltage);
  if (current === null) return null;
  const previous = toFiniteVoltage(previousVoltage);
  if (current === 0 && previous !== 0) return "loss";
  if (previous === 0 && current > 0) return "restored";
  return null;
}

function toFiniteVoltage(value) {
  if (value == null || value === "" || typeof value === "boolean") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}
