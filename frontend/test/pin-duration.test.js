import assert from "node:assert/strict";
import test from "node:test";
import { toDurationHours } from "../src/components/sidebar-right/pin-duration.js";

test("normaliza horas y días al contrato de horas de la API", () => {
  assert.equal(toDurationHours(8, "hours"), 8);
  assert.equal(toDurationHours(2, "days"), 48);
  assert.equal(toDurationHours(30, "days"), 720);
});

test("rechaza duraciones fuera del límite o no enteras", () => {
  assert.throws(() => toDurationHours(31, "days"), /30 días/);
  assert.throws(() => toDurationHours(721, "hours"), /720 horas/);
  assert.throws(() => toDurationHours(1.5, "hours"), /número entero/);
});
