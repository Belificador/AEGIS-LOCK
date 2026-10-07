const SESSION_KEY = "aegis.prototype.session.v2";
const DEFAULT_AUTH_ENDPOINT = "https://aegis-lock-api.onrender.com/api/login";
const AUTH_ENDPOINT = import.meta.env.VITE_AUTH_API_URL || DEFAULT_AUTH_ENDPOINT;
const REFRESH_ENDPOINT = AUTH_ENDPOINT.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "/api/v1/auth/refresh");
const LOGOUT_ENDPOINT = AUTH_ENDPOINT.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "/api/v1/auth/logout");
import { primeAlertAudio } from "./components/sidebar-right/critical-alert.js";
let activeSession = null;
let refreshTimer = null;

export function initializeAuth({ onAuthenticated }) {
  const loginView = document.querySelector("#login-view");
  const intro = document.querySelector("#intro-enter");
  const formPanel = document.querySelector("#login-panel");
  const form = document.querySelector("#login-form");
  const error = document.querySelector("#login-error");
  const button = document.querySelector("#login-submit");
  const video = document.querySelector("#intro-video");
  const modeLabel = document.querySelector("#auth-mode-label");
  modeLabel.innerHTML = '<span class="status-led led-normal"></span> AUTENTICACIÓN EN API AEGIS';
  video.addEventListener("ended", () => revealLogin());
  video.addEventListener("error", showVideoFallback);
  if (video.error) showVideoFallback();

  intro.addEventListener("pointerdown", skipIntro);
  function showVideoFallback() {
    revealLogin({ immediate: true });
  }

  intro.addEventListener("click", skipIntro);

  function skipIntro() {
    video.pause();
    revealLogin({ immediate: true });
  }

  function revealLogin({ immediate = false } = {}) {
    if (!formPanel.hidden) return;
    if (immediate) {
      formPanel.classList.add("is-instant");
      formPanel.hidden = false;
      intro.hidden = true;
      intro.classList.remove("is-leaving");
      document.querySelector("#login-username").focus();
      return;
    }
    intro.classList.add("is-leaving");
    formPanel.hidden = false;
    window.setTimeout(() => {
      intro.hidden = true;
      document.querySelector("#login-username").focus();
    }, 260);
  }

  document.querySelector("#login-back").addEventListener("click", () => {
    formPanel.hidden = true;
    formPanel.classList.remove("is-instant");
    intro.hidden = false;
    intro.classList.remove("is-leaving");
    error.textContent = "";
    restartIntro();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    primeAlertAudio();
    error.textContent = "";
    button.disabled = true;
    button.classList.add("is-busy");
    const fields = new FormData(form);
    try {
      const session = await authenticateRemote(fields);
      saveSession(session);
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
      if (session?.user && ["operator", "admin", "viewer"].includes(session.user.role) && session?.access_token) {
        activeSession = session;
        scheduleRefresh();
        onAuthenticated(session.user, session);
      } else {
        sessionStorage.removeItem(SESSION_KEY);
      }
    } catch {
      sessionStorage.removeItem(SESSION_KEY);
    }
  }

  function logout() {
    window.clearTimeout(refreshTimer);
    refreshTimer = null;
    const sessionToRevoke = activeSession;
    activeSession = null;
    sessionStorage.removeItem(SESSION_KEY);
    formPanel.hidden = true;
    formPanel.classList.remove("is-instant");
    intro.hidden = false;
    intro.classList.remove("is-leaving");
    loginView.hidden = false;
    error.textContent = "Sesión finalizada.";
    if (sessionToRevoke?.access_token && sessionToRevoke?.refresh_token) {
      void fetch(LOGOUT_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: sessionToRevoke.refresh_token }),
        keepalive: true,
      }).catch(() => {});
    }
    restartIntro();
  }

  function restartIntro() {
    if (!video.error) {
      try { video.currentTime = 0; } catch { /* Video metadata may still be loading. */ }
      video.play().catch(() => {});
    }
  }

  function saveSession(session) {
    activeSession = session;
    session.issued_at = Date.now();
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    scheduleRefresh();
  }

  function scheduleRefresh() {
    window.clearTimeout(refreshTimer);
    refreshTimer = null;
    if (!activeSession?.refresh_token) return;
    const expiresIn = Number(activeSession.expires_in) || 900;
    const issuedAt = Number(activeSession.issued_at) || 0;
    const refreshAt = issuedAt ? issuedAt + expiresIn * 1000 - 60_000 : Date.now() + 1000;
    refreshTimer = window.setTimeout(refreshAccessToken, Math.max(1000, refreshAt - Date.now()));
  }

  async function refreshAccessToken() {
    if (!activeSession?.refresh_token) return;
    try {
      const response = await fetch(REFRESH_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: activeSession.refresh_token }),
      });
      const result = await response.json().catch(() => ({}));
      const payload = result.data && typeof result.data === "object" ? result.data : result;
      if (!response.ok) {
        if (response.status === 401) {
          logout();
          window.location.reload();
          return;
        }
        throw new Error("No se pudo renovar la sesión.");
      }
      if (typeof payload.access_token !== "string" || typeof payload.refresh_token !== "string") {
        throw new Error("El backend devolvió una sesión incompleta.");
      }
      activeSession.access_token = payload.access_token;
      activeSession.refresh_token = payload.refresh_token;
      activeSession.expires_in = payload.expires_in;
      activeSession.issued_at = Date.now();
      if (payload.user) activeSession.user = payload.user;
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(activeSession));
      scheduleRefresh();
    } catch {
      refreshTimer = window.setTimeout(refreshAccessToken, 30_000);
    }
  }

  restoreSession();
  return { logout };
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
  const payload = result.data && typeof result.data === "object" ? result.data : result;
  if (!response.ok) throw new Error(result.detail || payload.detail || "Credenciales o perfil no válidos.");
  const serverUser = payload.user || result.user || {};
  const role = serverUser.role;
  if (!["operator", "admin", "viewer"].includes(role)) {
    throw new Error("La cuenta no tiene un perfil de Operador o Administrador asignado.");
  }
  const accessToken = payload.access_token || payload.token || result.access_token;
  if (typeof accessToken !== "string" || !accessToken) {
    throw new Error("El endpoint de Render no devolvió un token de acceso.");
  }
  return {
    demo: false,
    access_token: accessToken,
    refresh_token: payload.refresh_token || result.refresh_token || null,
    expires_in: payload.expires_in || result.expires_in || 900,
    user: {
      id: serverUser.id || payload.sub || result.sub || "authenticated-user",
      username: serverUser.username || serverUser.email || String(fields.get("username")),
      role,
    },
  };
}
