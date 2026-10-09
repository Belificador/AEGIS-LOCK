import assert from "node:assert/strict";
import test from "node:test";
import { formatActivity } from "../src/components/sidebar-right/activity-feed.js";

test("resume accesos autorizados y denegados con prioridad", () => {
  const authorized = formatActivity({ tipo_evento: "acceso_pin", valor: "GRANTED", zona: "Puerta Principal" });
  assert.equal(authorized.title, "Acceso autorizado");
  assert.equal(authorized.detail, "Puerta Principal · PIN temporal");
  assert.equal(authorized.priority, "success");

  const denied = formatActivity({ tipo_evento: "acceso_pin", valor: "DENIED", zona: "Puerta Principal" });
  assert.equal(denied.title, "Acceso denegado");
  assert.equal(denied.priority, "critical");
});

test("presenta movimiento, cámara y señales sin serializar objetos JSON", () => {
  const motion = formatActivity({ tipo_evento: "motion_detected", metadata: { camera_id: "CAM_03_OFICINA_L1" } });
  assert.equal(motion.title, "Movimiento detectado");
  assert.equal(motion.detail, "Cámara Oficina L1");

  const temperature = formatActivity({ tipo_evento: "temperatura", temperature_c: 39, zona: "Oficina L1" }, {
    alerts: [{ severity: "critical", message: "Temperatura crítica: 39 °C" }],
  });
  assert.equal(temperature.priority, "critical");
  assert.equal(temperature.detail.includes("[object Object]"), false);
  assert.equal(temperature.detail.includes("Temperatura crítica: 39 °C"), true);
});

test("convierte cambios locales de modo en actividad natural", () => {
  const closure = formatActivity({ kind: "local_mode", mode: "CIERRE DE JORNADA", actor: "admin", source: "CIERRE PROGRAMADO" });
  assert.equal(closure.title, "Cierre de jornada");
  assert.equal(closure.detail, "Activado por admin · CIERRE PROGRAMADO");
  assert.equal(closure.priority, "warning");
});
