export function buildArgusGreeting(user, now = new Date()) {
  const hour = now.getHours();
  const greeting = hour < 12 ? "Buenos días" : hour < 19 ? "Buenas tardes" : "Buenas noches";
  const displayName = String(user?.username || user?.name || "").trim();
  const localTime = new Intl.DateTimeFormat("es", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(now);
  const person = displayName ? `, ${displayName}` : "";
  return `${greeting}${person}. Son las ${localTime} en tu hora local. Argus está activo y listo para consultar el estado y la bitácora de AEGIS.`;
}
