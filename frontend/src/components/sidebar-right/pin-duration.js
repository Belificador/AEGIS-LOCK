export function toDurationHours(value, unit) {
  const amount = Number(value);
  if (!Number.isInteger(amount) || amount < 1) throw new Error("La duración debe ser un número entero positivo.");
  if (unit === "days") {
    if (amount > 30) throw new Error("La duración máxima es de 30 días.");
    return amount * 24;
  }
  if (unit !== "hours" || amount > 720) throw new Error("La duración máxima es de 720 horas.");
  return amount;
}
