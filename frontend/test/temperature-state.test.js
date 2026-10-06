import assert from "node:assert/strict";
import test from "node:test";

import { classifyTemperature } from "../src/components/sidebar-left/metrics/temperature-state.js";

test("comfort band colors high/low readings amber and critical heat red", () => {
  assert.deepEqual(classifyTemperature({ temperature_c: 24 }), {
    warning: false,
    critical: false,
    description: "TEMPERATURA NORMAL",
  });
  assert.equal(classifyTemperature({ temperature_c: 27 }).warning, true);
  assert.equal(classifyTemperature({ temperature_c: 21 }).warning, true);
  assert.equal(classifyTemperature({ temperature_c: 39 }).critical, true);
});

test("simulator comfort direction overrides the dashboard fallback band", () => {
  assert.equal(classifyTemperature({ temperature_c: 25, metadata: { direccion: 1 } }).warning, true);
  assert.equal(classifyTemperature({ temperature_c: 20, metadata: { direccion: 0 } }).warning, false);
});
