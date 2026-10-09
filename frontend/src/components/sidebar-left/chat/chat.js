export function mountChat(root, getContext) {
  root.innerHTML = `
    <section class="chat-panel" aria-labelledby="assistant-title">
      <div class="chat-panel-heading">
        <div class="chat-title-wrap"><span class="chat-ai-symbol" aria-hidden="true">✳</span><div><h2 id="assistant-title">Asistente de seguridad</h2><p>IA LOCAL · AÚN NO CONECTADA</p></div></div>
        <span class="mono eyebrow">AI / DEMO</span>
      </div>
      <div id="chat-thread" class="chat-thread" role="log" aria-live="polite">
        <p class="chat-prompt">Modelo no conectado. El asistente no tiene telemetría para consultar todavía.</p>
      </div>
      <form id="assistant-form" class="chat-form">
        <label class="visually-hidden" for="assistant-message">Consulta al asistente</label>
        <input id="assistant-message" name="message" maxlength="500" placeholder="Escribe una consulta…" autocomplete="off" required />
        <button class="chat-send" type="submit" aria-label="Enviar mensaje">↑</button>
      </form>
    </section>`;

  const thread = root.querySelector("#chat-thread");
  const form = root.querySelector("#assistant-form");
  const input = root.querySelector("#assistant-message");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    appendMessage(message, "user");
    input.value = "";
    form.querySelector("button").disabled = true;
    await new Promise((resolve) => window.setTimeout(resolve, 350));
    appendMessage(makeResponse(message, getContext()), "assistant");
    form.querySelector("button").disabled = false;
    input.focus();
  });

  function appendMessage(text, type) {
    thread.querySelector(".chat-prompt")?.remove();
    const bubble = document.createElement("div");
    bubble.className = `chat-message ${type === "user" ? "is-user" : "is-assistant"}`;
    bubble.textContent = text;
    thread.append(bubble);
    thread.scrollTop = thread.scrollHeight;
  }
}

function makeResponse(message, context) {
  if (!context.modelConnected) {
    return "Modelo no conectado. No hay lecturas disponibles para informar.";
  }
  const normalized = message.toLocaleLowerCase("es");
  if (/clave|contraseña|puerta|cerradura|luz|apaga|enc[end]/.test(normalized)) {
    return "La IA local todavía no está conectada. No se cambiaron claves ni se enviaron comandos a puertas o luces.";
  }
  if (/alerta|reporte|incidente/.test(normalized)) {
    return context.recentAlerts.length
      ? `Reporte de alertas recientes:\n${context.recentAlerts.map((alert) => `• ${alert}`).join("\n")}`
      : "No se han recibido alertas en los eventos del modelo.";
  }
  if (/gerencia|estado|temperatura|aforo|ocupaci[oó]n/.test(normalized)) {
    const telemetry = context.telemetry || {};
    const temperature = telemetry.temperature_c == null ? "sin lectura" : `${telemetry.temperature_c} °C`;
    const occupancy = telemetry.occupancy == null ? "sin lectura" : `${telemetry.occupancy} personas`;
    const source = telemetry.source_id ? ` · fuente ${telemetry.source_id}` : "";
    return `Estado recibido${source}: temperatura ${temperature}; aforo ${occupancy}.`;
  }
  return "Asistente local no conectado. No se ejecutaron acciones ni se inventaron lecturas.";
}
