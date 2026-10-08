import { buildArgusGreeting } from "./greeting.js";

const AUTH_URL = import.meta.env.VITE_AUTH_API_URL || "https://aegis-lock-api.onrender.com/api/login";
const API_ROOT = AUTH_URL.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");

export function mountChat(root, session, user) {
  root.innerHTML = `
    <section class="chat-panel" aria-labelledby="assistant-title">
      <div class="chat-panel-heading">
        <div class="chat-title-wrap"><span class="chat-ai-symbol" aria-hidden="true">✳</span><div><h2 id="assistant-title">ARGUS · ASISTENTE AEGIS</h2><p>OPENROUTER · HERRAMIENTAS AUTORIZADAS</p></div></div>
        <span class="mono eyebrow">AI / ARGUS</span>
      </div>
      <div id="chat-thread" class="chat-thread" role="log" aria-live="polite">
        <p class="chat-prompt">ARGUS consulta señales y bitácora de AEGIS. Las acciones disponibles dependen de tu rol.</p>
      </div>
      <form id="assistant-form" class="chat-form">
        <label class="visually-hidden" for="assistant-message">Consulta a Argus</label>
        <input id="assistant-message" name="message" maxlength="1200" placeholder="Consulta estado, bitácora o cámaras…" autocomplete="off" required />
        <button class="chat-send" type="submit" aria-label="Enviar mensaje">↑</button>
      </form>
    </section>`;

  const thread = root.querySelector("#chat-thread");
  const form = root.querySelector("#assistant-form");
  const input = root.querySelector("#assistant-message");
  const prompt = thread.querySelector(".chat-prompt");
  const listeners = new AbortController();

  function updateGreeting() {
    if (prompt?.isConnected) prompt.textContent = buildArgusGreeting(user);
  }

  updateGreeting();
  input.addEventListener("focus", updateGreeting, { signal: listeners.signal });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) updateGreeting();
  }, { signal: listeners.signal });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    appendMessage(message, "user");
    input.value = "";
    form.querySelector("button").disabled = true;
    try {
      if (!session?.access_token) throw new Error("Inicia sesión para consultar Argus.");
      const response = await fetch(`${API_ROOT}/api/v1/chat`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ message }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Argus no está disponible ahora.");
      appendMessage(payload.response || "Argus no devolvió texto.", "assistant");
    } catch (error) {
      appendMessage(error.message || "No fue posible consultar Argus.", "assistant");
    }
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

  return { destroy() { listeners.abort(); } };
}
