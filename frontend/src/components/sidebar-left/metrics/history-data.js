export function formatValue(value, digits = 1) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("es", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(Number(value));
}
