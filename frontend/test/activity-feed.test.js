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

test("un voltaje nulo no se presenta como corte; una lectura cero explícita sí", () => {
  const missing = formatActivity({ tipo_evento: "voltaje", voltage_v: null, valor: null });
  assert.equal(missing.title, "Voltaje sin lectura");
  assert.equal(missing.priority, "system");

  const loss = formatActivity({ tipo_evento: "voltaje", voltage_v: 0, valor: 0 });
  assert.equal(loss.title, "Corte de energía");
  assert.equal(loss.priority, "critical");

  const fluctuation = formatActivity({ tipo_evento: "voltaje", voltage_v: 105 }, {
    alerts: [{ code: "VOLTAGE_FLUCTUATION", severity: "warning", message: "Fluctuación de voltaje" }],
  });
  assert.equal(fluctuation.title, "Fluctuación de voltaje");
  assert.equal(fluctuation.priority, "warning");
});

test("no presenta un voltage null como corte eléctrico y distingue una fluctuación validada", () => {
  const missingVoltage = formatActivity({ tipo_evento: "voltaje", voltage_v: null, valor: null });
  assert.equal(missingVoltage.title, "Voltaje sin lectura");
  assert.equal(missingVoltage.priority, "system");

  const powerLoss = formatActivity({ tipo_evento: "voltaje", voltage_v: 0, valor: 0 });
  assert.equal(powerLoss.title, "Corte de energía");
  assert.equal(powerLoss.priority, "critical");

  const fluctuation = formatActivity({ tipo_evento: "voltaje", voltage_v: 105, valor: 105 }, {
    alerts: [{ code: "VOLTAGE_FLUCTUATION", severity: "warning", message: "Fluctuación de voltaje" }],
  });
  assert.equal(fluctuation.title, "Fluctuación de voltaje");
  assert.equal(fluctuation.priority, "warning");
});

test("convierte cambios locales de modo en actividad natural", () => {
  const closure = formatActivity({ kind: "local_mode", mode: "CIERRE DE JORNADA", actor: "admin", source: "CIERRE PROGRAMADO" });
  assert.equal(closure.title, "Cierre de jornada");
  assert.equal(closure.detail, "Activado por admin · CIERRE PROGRAMADO");
  assert.equal(closure.priority, "warning");
});

test("muestra el cero de iluminación y separa acciones de movimiento del aforo real", () => {
  const lightsOff = formatActivity({
    tipo_evento: "iluminacion",
    valor: 0,
    illumination_percent: 0,
    zona: "Administración",
  });
  assert.equal(lightsOff.title, "Iluminación actualizada");
  assert.equal(lightsOff.detail, "0 % luz · Administración");

  const stopCommand = formatActivity({
    tipo_evento: "aforo",
    valor: 0,
    metadata: { accion: "frenar" },
  });
  assert.equal(stopCommand.title, "Acción del modelo");
  assert.equal(stopCommand.detail, "frenar");
});
