import assert from "node:assert/strict";
import test from "node:test";

import { validateDemoCredentials } from "../src/demo-auth.js";

test("acepta las credenciales demo del Operador y Administrador", () => {
  assert.deepEqual(validateDemoCredentials("operador", "AegisOperador2026!"), {
    username: "operador",
    role: "operator",
  });
  assert.deepEqual(validateDemoCredentials("admin", "AegisAdmin2026!"), {
    username: "admin",
    role: "admin",
  });
});

test("rechaza credenciales y perfiles que no coinciden", () => {
  assert.throws(() => validateDemoCredentials("operador", "incorrecta"));
  assert.throws(() => validateDemoCredentials("invitado", "AegisAdmin2026!"));
});
