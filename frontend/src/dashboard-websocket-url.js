const DEFAULT_AUTH_URL = "https://aegis-lock-api.onrender.com/api/login";

export function resolveDashboardWebSocketUrl(configuredUrl, authUrl = DEFAULT_AUTH_URL) {
  const apiRoot = String(authUrl || DEFAULT_AUTH_URL)
    .replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");
  const api = new URL(apiRoot);
  if (api.protocol !== "http:" && api.protocol !== "https:") {
    throw new TypeError("VITE_AUTH_API_URL debe usar HTTP o HTTPS.");
  }

  const expected = new URL(api.origin);
  expected.protocol = api.protocol === "https:" ? "wss:" : "ws:";
  expected.pathname = "/ws/dashboard";

  if (!configuredUrl) return expected.href;
  try {
    const configured = new URL(configuredUrl);
    const expectedOrigin = `${api.protocol}//${api.host}`;
    const configuredOrigin = `${configured.protocol === "wss:" ? "https:" : "http:"}//${configured.host}`;
    if (
      configured.pathname === "/ws/dashboard"
      && configuredOrigin === expectedOrigin
      && ["ws:", "wss:"].includes(configured.protocol)
    ) return configured.href;
  } catch {
    // Fall through to the dashboard socket derived from the API URL.
  }

  console.warn("VITE_WS_URL no apunta al WebSocket /ws/dashboard del API; usando la URL derivada de VITE_AUTH_API_URL.");
  return expected.href;
}
