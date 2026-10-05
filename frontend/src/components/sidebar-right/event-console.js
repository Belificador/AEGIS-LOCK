export function mountEventConsole(root) {
  root.innerHTML = `
    <section class="panel-card events-panel" aria-labelledby="events-title">
      <div class="panel-heading"><span id="events-title">Consola de eventos</span><span class="events-live"><i class="status-led led-offline"></i><span id="events-connection-label">MODELO NO CONECTADO</span></span></div>
      <div id="event-console" class="event-console" role="log" aria-live="polite" aria-label="Flujo de eventos JSON"><p id="event-empty" class="event-empty"><span>MODELO NO CONECTADO · ESPERANDO SEÑAL</span><i aria-hidden="true"></i><i aria-hidden="true"></i><i aria-hidden="true"></i></p></div>
      <div class="event-footer"><span id="event-count">0 EVENTOS</span><span>JSON · VALIDADO</span></div>
    </section>`;
  const consoleRoot = root.querySelector("#event-console");
  const count = root.querySelector("#event-count");
  let eventCount = 0;

  function append(data, severity = "normal") {
    const wasAtBottom = consoleRoot.scrollHeight - consoleRoot.clientHeight - consoleRoot.scrollTop < 24;
    consoleRoot.querySelector("#event-empty")?.remove();
    const line = document.createElement("p");
    line.className = `event-line${severity === "normal" ? "" : ` is-${severity}`}`;
    const time = document.createElement("time");
    time.textContent = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date());
    const text = document.createElement("span");
    const serialized = typeof data === "string" ? data : JSON.stringify(data);
    text.textContent = serialized;
    line.append(time, text);
    consoleRoot.append(line);
    if (wasAtBottom) consoleRoot.scrollTop = consoleRoot.scrollHeight;
    eventCount += 1;
    count.textContent = `${eventCount} EVENTO${eventCount === 1 ? "" : "S"}`;
  }

  return {
    append,
    setConnection(connected) {
      const label = root.querySelector("#events-connection-label");
      const led = root.querySelector(".events-live .status-led");
      label.textContent = connected ? "SEÑAL EN VIVO" : "MODELO NO CONECTADO";
      led.className = `status-led ${connected ? "led-normal" : "led-offline"}`;
    },
    alert(message, severity = "warning") { append({ type: "security_alert", message }, severity); },
  };
}
