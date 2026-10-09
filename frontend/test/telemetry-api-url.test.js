import test from "node:test";
import assert from "node:assert/strict";

import { resolveLatestTelemetryUrl } from "../src/telemetry-api-url.js";

test("derives the AEGIS latest-telemetry REST endpoint from the login URL", () => {
  assert.equal(
    resolveLatestTelemetryUrl("https://aegis-lock-api.onrender.com/api/login"),
    "https://aegis-lock-api.onrender.com/api/v1/telemetry/latest",
  );
});

test("uses HTTP for a local FastAPI REST endpoint", () => {
  assert.equal(
    resolveLatestTelemetryUrl("http://127.0.0.1:8000/api/v1/auth/login"),
    "http://127.0.0.1:8000/api/v1/telemetry/latest",
  );
});
