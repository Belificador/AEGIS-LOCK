import test from "node:test";
import assert from "node:assert/strict";

import { resolveDashboardWebSocketUrl } from "../src/dashboard-websocket-url.js";

test("uses the configured dashboard socket when it matches the API host and route", () => {
  assert.equal(
    resolveDashboardWebSocketUrl(
      "wss://api.example.test/ws/dashboard",
      "https://api.example.test/api/login",
    ),
    "wss://api.example.test/ws/dashboard",
  );
});

test("recovers a dashboard URL misconfigured to the telemetry-ingest route", () => {
  assert.equal(
    resolveDashboardWebSocketUrl(
      "wss://aegis-lock-api.onrender.com/ws/telemetry",
      "https://aegis-lock-api.onrender.com/api/login",
    ),
    "wss://aegis-lock-api.onrender.com/ws/dashboard",
  );
});

test("rejects a dashboard socket hosted on the gemelo service", () => {
  assert.equal(
    resolveDashboardWebSocketUrl(
      "wss://gemelo-digital-bhjp.onrender.com/ws/dashboard",
      "https://aegis-lock-api.onrender.com/api/login",
    ),
    "wss://aegis-lock-api.onrender.com/ws/dashboard",
  );
});

test("derives websocket scheme and route from a local AEGIS API URL", () => {
  assert.equal(
    resolveDashboardWebSocketUrl("", "http://127.0.0.1:8000/api/login"),
    "ws://127.0.0.1:8000/ws/dashboard",
  );
});
