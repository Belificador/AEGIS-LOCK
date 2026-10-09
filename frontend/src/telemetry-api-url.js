const DEFAULT_AUTH_URL = "https://aegis-lock-api.onrender.com/api/login";

export function resolveLatestTelemetryUrl(authUrl = DEFAULT_AUTH_URL) {
  const apiRoot = String(authUrl || DEFAULT_AUTH_URL)
    .replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");
  const api = new URL(apiRoot);
  if (api.protocol !== "http:" && api.protocol !== "https:") {
    throw new TypeError("VITE_AUTH_API_URL debe usar HTTP o HTTPS.");
  }
  api.pathname = "/api/v1/telemetry/latest";
  api.search = "";
  api.hash = "";
  return api.href;
}
