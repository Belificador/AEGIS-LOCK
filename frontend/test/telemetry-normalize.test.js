import test from "node:test";
import assert from "node:assert/strict";

import { normalizeTelemetry } from "../src/dataReceiver.js";

test("preserves zero occupancy as a valid current state", () => {
  const event = normalizeTelemetry({
    tipo_evento: "aforo",
    valor: 0,
    metadata: { estado_actual: true },
  });
  assert.equal(event.occupancy, 0);
});

test("does not convert an occupancy action into the current people count", () => {
  const event = normalizeTelemetry({
    tipo_evento: "aforo",
    valor: 0,
    metadata: { accion: "frenar", enviados: 0 },
  });
  assert.equal(event.valor, 0);
  assert.equal(event.occupancy, undefined);
});

test("normalizes a zero-light event to an explicit zero percent", () => {
  const event = normalizeTelemetry({
    tipo_evento: "iluminacion",
    valor: 0,
    metadata: { factor_electrico: 0, unidad: "%" },
  });
  assert.equal(event.illumination_percent, 0);
});
