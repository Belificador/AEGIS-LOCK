import test from "node:test";
import assert from "node:assert/strict";

import { classifyPowerLossTransition } from "../src/components/viewport/power-loss-transition.js";

test("emits one power-loss transition and one recovery transition per voltage state change", () => {
  assert.equal(classifyPowerLossTransition(null, 0), "loss");
  assert.equal(classifyPowerLossTransition(0, 0), null);
  assert.equal(classifyPowerLossTransition(0, 220), "restored");
  assert.equal(classifyPowerLossTransition(220, 220), null);
});

test("does not infer power loss from missing or invalid voltage readings", () => {
  assert.equal(classifyPowerLossTransition(null, null), null);
  assert.equal(classifyPowerLossTransition(220, ""), null);
  assert.equal(classifyPowerLossTransition(220, "not-a-voltage"), null);
});
