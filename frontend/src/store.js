const listeners = new Set();

export const state = {
  user: null,
  mode: "NORMAL",
  modeSource: "",
  connection: "MODEL_DISCONNECTED",
  modelConnected: false,
  telemetry: { energy_kwh: null, power_kw: null, voltage_v: null, occupancy: null, temperature_c: null },
  recentAlerts: [],
};

export function patchState(values) {
  Object.assign(state, values);
  for (const listener of listeners) listener(state);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
