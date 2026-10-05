const SESSION_KEY = "aegis.prototype.session.v2";
const AUTH_ENDPOINT = import.meta.env.VITE_AUTH_API_URL || "";
import { validateDemoCredentials } from "./demo-auth.js";

export function initializeAuth({ onAuthenticated }) {
  const loginView = document.querySelector("#login-view");
  const intro = document.querySelector("#intro-enter");
  const formPanel = document.querySelector("#login-panel");
  const form = document.querySelector("#login-form");
  const error = document.querySelector("#login-error");
  const button = document.querySelector("#login-submit");
  const video = document.querySelector("#intro-video");
  const modeLabel = document.querySelector("#auth-mode-label");
  let introVideoReady = video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA && !video.error;

  if (AUTH_ENDPOINT) {
    modeLabel.innerHTML = '<span class="status-led led-normal"></span> AUTENTICACIÓN REST CONFIGURADA';
    document.querySelector("#demo-account-hint").hidden = true;
  }
  video.addEventListener("ended", revealLogin);
  video.addEventListener("canplay", () => {
    introVideoReady = true;
  });
  video.addEventListener("error", showVideoFallback);
  if (video.error) showVideoFallback();

  function showVideoFallback() {
    introVideoReady = false;
    revealLogin();
  }

  intro.addEventListener("click", () => {
    if (introVideoReady || !video.error) {
      if (video.paused) video.play().catch(() => {});
      return;
    }
    revealLogin();
  });

  function revealLogin() {
    if (!formPanel.hidden) return;
    intro.classList.add("is-leaving");
    formPanel.hidden = false;
    window.setTimeout(() => {
      intro.hidden = true;
      document.querySelector("#login-username").focus();
    }, 260);
  }

  document.querySelector("#login-back").addEventListener("click", () => {
    formPanel.hidden = true;
    intro.hidden = false;
    intro.classList.remove("is-leaving");
    error.textContent = "";
    restartIntro();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    button.disabled = true;
    button.classList.add("is-busy");
    const fields = new FormData(form);
    try {
      const session = AUTH_ENDPOINT
        ? await authenticateRemote(fields)
        : await authenticatePrototype(fields);
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
      onAuthenticated(session.user, session);
    } catch (caught) {
      error.textContent = caught.message || "No se pudo validar el acceso.";
    } finally {
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  });

  function restoreSession() {
    try {
      const session = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
      if (session?.user && ["operator", "admin"].includes(session.user.role)) onAuthenticated(session.user, session);
    } catch {
      sessionStorage.removeItem(SESSION_KEY);
    }
  }

  function logout() {
    sessionStorage.removeItem(SESSION_KEY);
    formPanel.hidden = true;
    intro.hidden = false;
    intro.classList.remove("is-leaving");
    loginView.hidden = false;
    error.textContent = "Sesión finalizada.";
    restartIntro();
  }

  function restartIntro() {
    if (!video.error) {
      try { video.currentTime = 0; } catch { /* Video metadata may still be loading. */ }
      video.play().catch(() => {});
    }
  }

  restoreSession();
  return { logout };
}

async function authenticatePrototype(fields) {
  const username = String(fields.get("username") || "").trim();
  const password = String(fields.get("password") || "");
  const account = validateDemoCredentials(username, password);
  await new Promise((resolve) => window.setTimeout(resolve, 380));
  return {
    demo: true,
    access_token: null,
    user: { id: `local-${account.role}`, username: account.username, role: account.role },
  };
}

async function authenticateRemote(fields) {
  let response;
  try {
    response = await fetch(AUTH_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: String(fields.get("username")).trim(),
        password: String(fields.get("password")),
      }),
    });
  } catch {
    throw new Error("No se pudo conectar con el endpoint de autenticación configurado.");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || "Credenciales o perfil no válidos.");
  const serverUser = result.user || {};
  const role = serverUser.role;
  if (!["operator", "admin"].includes(role)) {
    throw new Error("La cuenta no tiene un perfil de Operador o Administrador asignado.");
  }
  return {
    demo: false,
    access_token: result.access_token || null,
    refresh_token: result.refresh_token || null,
    user: {
      id: serverUser.id || result.sub || "authenticated-user",
      username: serverUser.email || serverUser.username || String(fields.get("username")),
      role,
    },
  };
}
