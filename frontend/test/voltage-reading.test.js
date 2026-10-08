import assert from "node:assert/strict";
import test from "node:test";

import { getVoltageReading, VOLTAGE_NORMAL_MAX_V, VOLTAGE_NORMAL_MIN_V } from "../src/voltage-reading.js";


test("missing, null, empty and non-finite voltage values are not treated as zero", () => {
  assert.equal(getVoltageReading({ voltage_v: null }), null);
  assert.equal(getVoltageReading({}), null);
  assert.equal(getVoltageReading({ tipo_evento: "voltaje", valor: null }), null);
  assert.equal(getVoltageReading({ tipo_evento: "voltage", valor: "" }), null);
  assert.equal(getVoltageReading({ tipo_evento: "voltage", valor: "NaN" }), null);
  assert.equal(getVoltageReading({ event_type: "telemetry", voltage_v: null, valor: 24 }), null);
});


test("explicit zero and scalar voltage readings remain detectable", () => {
  assert.equal(getVoltageReading({ voltage_v: 0 }), 0);
  assert.equal(getVoltageReading({ tipo_evento: "voltaje", valor: { voltage_v: 220 } }), 220);
  assert.equal(getVoltageReading({ event_type: "voltage", valor: "110" }), 110);
});


test("a generic event's nullable voltage field is not interpreted as a measurement", () => {
  assert.equal(getVoltageReading({ event_type: "telemetry", voltage_v: null, valor: 23 }), null);
});


test("configured voltage band is inclusive", () => {
  assert.equal(VOLTAGE_NORMAL_MIN_V, 110);
  assert.equal(VOLTAGE_NORMAL_MAX_V, 220);
  assert.ok(getVoltageReading({ voltage_v: 110 }) >= VOLTAGE_NORMAL_MIN_V);
  assert.ok(getVoltageReading({ voltage_v: 220 }) <= VOLTAGE_NORMAL_MAX_V);
});
