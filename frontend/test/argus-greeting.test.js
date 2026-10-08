import test from "node:test";
import assert from "node:assert/strict";

import { buildArgusGreeting } from "../src/components/sidebar-left/chat/greeting.js";

test("greets with the local morning period and account name", () => {
  assert.equal(
    buildArgusGreeting({ username: "operador" }, new Date(2026, 9, 8, 9, 5)),
    "Buenos días, operador. Son las 09:05 en tu hora local. Argus está activo y listo para consultar el estado y la bitácora de AEGIS.",
  );
});

test("uses afternoon and evening greetings according to local hour", () => {
  assert.match(buildArgusGreeting({}, new Date(2026, 9, 8, 15, 0)), /^Buenas tardes\./);
  assert.match(buildArgusGreeting({}, new Date(2026, 9, 8, 20, 0)), /^Buenas noches\./);
});
