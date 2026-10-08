import test from "node:test";
import assert from "node:assert/strict";

import { reduceGlobalAlerts } from "../src/components/global-alert-banner.js";

test("keeps a power loss banner active until positive voltage arrives", () => {
  const lost = reduceGlobalAlerts(new Map(), { event: { source_id: "meter", zone: "Gerencia", tipo_evento: "voltaje", voltage_v: 0 } });
  assert.equal(lost.has("POWER_LOSS:meter:Gerencia"), true);

  const restored = reduceGlobalAlerts(lost, { event: { source_id: "meter", zone: "Gerencia", tipo_evento: "voltaje", voltage_v: 220 } });
  assert.equal(restored.has("POWER_LOSS:meter:Gerencia"), false);
});

test("keeps an out-of-range voltage banner until voltage returns to normal", () => {
  const fluctuating = reduceGlobalAlerts(new Map(), { event: { source_id: "meter", zone: "L1", tipo_evento: "voltaje", voltage_v: 95 } });
  assert.equal(fluctuating.has("VOLTAGE_FLUCTUATION:meter:L1"), true);

  const normal = reduceGlobalAlerts(fluctuating, { event: { source_id: "meter", zone: "L1", tipo_evento: "voltaje", voltage_v: 120 } });
  assert.equal(normal.has("VOLTAGE_FLUCTUATION:meter:L1"), false);
});

test("keeps denied access visible until an authorized access resolves it", () => {
  const denied = reduceGlobalAlerts(new Map(), { event: { source_id: "door", zone: "Recepción", tipo_evento: "acceso_pin", valor: "DENIED" } });
  assert.equal(denied.has("ACCESS_DENIED:door:Recepción"), true);

  const granted = reduceGlobalAlerts(denied, { event: { source_id: "door", zone: "Recepción", tipo_evento: "acceso_pin", valor: "GRANTED" } });
  assert.equal(granted.has("ACCESS_DENIED:door:Recepción"), false);
});
