import { formatActivity } from "./activity-feed.js";

const MAX_VISIBLE_ACTIVITIES = 120;

export function mountEventConsole(root) {
  root.innerHTML = `
    <section class="panel-card events-panel" aria-labelledby="events-title">
      <div class="panel-heading"><span id="events-title">Bitácora de actividad</span><span class="events-live"><i class="status-led led-offline"></i><span id="events-connection-label">MODELO NO CONECTADO</span></span></div>
      <div id="event-console" class="event-console activity-feed" role="log" aria-live="polite" aria-relevant="additions" aria-label="Bitácora cronológica de actividad"><p id="event-empty" class="event-empty"><span>MODELO NO CONECTADO · ESPERANDO ACTIVIDAD</span><i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i></p></div>
      <div class="event-footer"><span id="event-count">0 ACTIVIDADES</span><span>MÁS RECIENTE PRIMERO</span></div>
    </section>`;
  const consoleRoot = root.querySelector("#event-console");
  const count = root.querySelector("#event-count");
  let eventCount = 0;

  function append(data, options = {}) {
    if (typeof options === "string") options = { priority: options };
    const activity = formatActivity(data, options);
    const parsedDate = new Date(activity.timestamp);
    const date = Number.isNaN(parsedDate.getTime()) ? new Date() : parsedDate;
    const wasAtTop = consoleRoot.scrollTop < 24;
    consoleRoot.querySelector("#event-empty")?.remove();
    const line = document.createElement("article");
    line.className = "event-line";
    line.dataset.priority = activity.priority;
    line.dataset.timestamp = String(date.getTime());
    const time = document.createElement("time");
    time.dateTime = date.toISOString();
    time.textContent = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
    time.title = new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "medium" }).format(date);
    const content = document.createElement("div");
    content.className = "activity-content";
    const badge = document.createElement("span");
    badge.className = "activity-badge";
    const marker = document.createElement("i");
    marker.setAttribute("aria-hidden", "true");
    const title = document.createElement("strong");
    title.className = "activity-title";
    title.textContent = activity.title;
    badge.append(marker, title);
    content.append(badge);
    if (activity.detail) {
      const detail = document.createElement("span");
      detail.className = "activity-detail";
      detail.textContent = activity.detail;
      content.append(detail);
    }
    line.append(time, content);

    const newerEntry = [...consoleRoot.querySelectorAll(".event-line")]
      .find((entry) => Number(entry.dataset.timestamp) < date.getTime());
    consoleRoot.insertBefore(line, newerEntry || null);
    if (consoleRoot.querySelectorAll(".event-line").length > MAX_VISIBLE_ACTIVITIES) consoleRoot.lastElementChild.remove();
    if (wasAtTop) consoleRoot.scrollTop = 0;
    eventCount += 1;
    count.textContent = `${eventCount} ACTIVIDAD${eventCount === 1 ? "" : "ES"}`;
  }

  return {
    append,
    setConnection(connected) {
      const label = root.querySelector("#events-connection-label");
      const led = root.querySelector(".events-live .status-led");
      label.textContent = connected ? "CONECTADO A RENDER" : "DESCONECTADO";
      led.className = `status-led ${connected ? "led-normal" : "led-offline"}`;
    },
    alert(message, severity = "warning") { append({ kind: "activity_alert", message }, { priority: severity }); },
  };
}
