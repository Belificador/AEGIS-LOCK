import { toDurationHours } from "./pin-duration.js";

const API_URL = import.meta.env.VITE_AUTH_API_URL || "https://aegis-lock-api.onrender.com/api/login";
const API_ROOT = API_URL.replace(/\/(?:api\/login|api\/v1\/auth\/login)\/?$/, "");

export function mountAdminDiagnostics({ session, onClose } = {}) {
  const dialog = document.createElement("dialog");
  dialog.className = "admin-diagnostics-dialog";
  dialog.setAttribute("aria-labelledby", "admin-diagnostics-title");
  dialog.innerHTML = `
    <div class="admin-diagnostics-shell">
      <header class="admin-diagnostics-header">
        <div><p class="eyebrow">AEGIS LOCK · SOLO ADMINISTRADOR</p><h2 id="admin-diagnostics-title">ANALÍTICA Y DIAGNÓSTICO</h2></div>
        <button class="icon-button" type="button" data-admin-close aria-label="Cerrar analítica">×</button>
      </header>
      <nav class="admin-diagnostics-tabs" role="tablist" aria-label="Herramientas de administrador">
        <button type="button" role="tab" data-tab="history" aria-selected="true">ANALÍTICA</button>
        <button type="button" role="tab" data-tab="errors" aria-selected="false">CAJA NEGRA</button>
        <button type="button" role="tab" data-tab="pins" aria-selected="false">PIN TEMPORAL</button>
      </nav>
      <section class="admin-diagnostics-panel" data-panel="history">
        <div class="admin-panel-toolbar"><span>Picos y muestras guardados en Render PostgreSQL</span><label>Periodo <select data-days><option value="1">24 horas</option><option value="7" selected>7 días</option><option value="30">30 días</option></select></label><button type="button" data-refresh-history>ACTUALIZAR</button></div>
        <div class="admin-peak-grid"><article><span>PICO TEMPERATURA</span><strong data-peak-temperature>—</strong><small data-peak-temperature-meta>Sin datos</small></article><article><span>PICO POTENCIA ESTIMADA</span><strong data-peak-power>—</strong><small data-peak-power-meta>Sin datos</small></article><article><span>ENERGÍA ACUMULADA</span><strong data-peak-energy>—</strong><small data-peak-energy-meta>Sin datos</small></article></div>
        <div class="admin-charts"><article><h3>Temperatura por muestra</h3><canvas data-chart="temperature" aria-label="Gráfica de temperatura recibida"></canvas></article><article><h3>Consumo estimado por muestra</h3><canvas data-chart="power" aria-label="Gráfica de potencia estimada recibida"></canvas></article></div>
        <h3 class="admin-subheading">TRAZABILIDAD RECIENTE</h3><div class="admin-table-wrap"><table><thead><tr><th>Fecha</th><th>Acción</th><th>Operador</th><th>Detalle</th></tr></thead><tbody data-audit-rows></tbody></table></div>
      </section>
      <section class="admin-diagnostics-panel" data-panel="errors" hidden>
        <div class="admin-panel-toolbar"><span>Errores HTTP, desconexiones y duración de sesión WebSocket</span><button type="button" data-refresh-errors>ACTUALIZAR</button></div>
        <div class="admin-table-wrap"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Descripción</th><th>Duración</th></tr></thead><tbody data-error-rows></tbody></table></div>
        <p class="admin-page-info" data-error-count></p>
        <button type="button" data-load-more-errors hidden>CARGAR MÁS ERRORES</button>
      </section>
      <section class="admin-diagnostics-panel" data-panel="pins" hidden>
        <form class="admin-pin-form" data-pin-form>
          <label>Puerta<select name="door_name" required></select></label>
          <label>Asignado a<input name="target_user" maxlength="120" placeholder="Nombre de visitante" required></label>
          <label>Duración<input name="duration_value" type="number" min="1" max="720" value="8" required></label>
          <label>Unidad<select name="duration_unit"><option value="hours">Horas</option><option value="days">Días</option></select></label>
          <button type="submit">GENERAR PIN</button>
        </form>
        <p class="admin-pin-note">El PIN se almacena cifrado en PostgreSQL y puede revocarse antes de vencer. “Asignado a” queda como dato de trazabilidad; el teclado actual valida el PIN, no la identidad de la persona.</p>
        <div class="admin-pin-result" data-pin-result hidden></div>
        <div class="admin-panel-toolbar"><h3>PINs temporales activos</h3><button type="button" data-refresh-pins>ACTUALIZAR</button></div>
        <div class="admin-table-wrap"><table><thead><tr><th>Puerta</th><th>PIN</th><th>Usuario destino</th><th>Creado por</th><th>Vence</th><th></th></tr></thead><tbody data-pin-rows></tbody></table></div>
      </section>
      <p class="admin-diagnostics-status" data-status role="status" aria-live="polite"></p>
    </div>`;
  document.body.append(dialog);

  const status = dialog.querySelector("[data-status]");
  const durationInput = dialog.querySelector('[name="duration_value"]');
  const durationUnit = dialog.querySelector('[name="duration_unit"]');
  const pinForm = dialog.querySelector("[data-pin-form]");
  let errorOffset = 0;

  function updateDurationLimit() {
    const days = durationUnit.value === "days";
    durationInput.max = days ? "30" : "720";
    durationInput.setAttribute("aria-label", days ? "Duración en días" : "Duración en horas");
    durationInput.value = String(Math.min(Number(durationInput.value) || 1, Number(durationInput.max)));
  }

  updateDurationLimit();
  durationUnit.addEventListener("change", updateDurationLimit);

  async function api(path, options = {}) {
    if (!session?.access_token) throw new Error("La sesión no incluye JWT de Aegis.");
    const response = await fetch(`${API_ROOT}/api/v1${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${session.access_token}`,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Error HTTP ${response.status}`);
    return payload;
  }

  function setStatus(message, error = false) {
    status.textContent = message || "";
    status.classList.toggle("is-error", error);
  }

  function addCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value == null ? "—" : String(value);
    row.append(cell);
    return cell;
  }

  function formatDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("es");
  }

  function peakText(peak, digits, unit) {
    return peak ? `${Number(peak.value).toFixed(digits)} ${unit}` : "—";
  }

  function drawChart(canvas, samples, key, color) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    context.clearRect(0, 0, rect.width, rect.height);
    const values = samples.map((sample) => sample[key]).filter((value) => Number.isFinite(Number(value)));
    if (values.length < 2) {
      context.fillStyle = "#8491a6";
      context.font = "11px sans-serif";
      context.fillText("Esperando muestras", 12, 24);
      return;
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || Math.max(Math.abs(max) * 0.08, 1);
    context.strokeStyle = "rgba(168,194,222,.15)";
    context.lineWidth = 1;
    for (let y = 12; y < rect.height; y += rect.height / 3) {
      context.beginPath(); context.moveTo(0, y); context.lineTo(rect.width, y); context.stroke();
    }
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    values.forEach((value, index) => {
      const x = 8 + index * (rect.width - 16) / (values.length - 1);
      const y = rect.height - 8 - ((value - min) / span) * (rect.height - 18);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  }

  async function loadHistory() {
    setStatus("Consultando historial…");
    try {
      const days = Number(dialog.querySelector("[data-days]").value) || 7;
      const data = await api(`/analytics/history?days=${days}&limit=1000`);
      const peaks = data.peaks || {};
      dialog.querySelector("[data-peak-temperature]").textContent = peakText(peaks.temperature, 1, "°C");
      dialog.querySelector("[data-peak-temperature-meta]").textContent = peaks.temperature
        ? `${peaks.temperature.zone} · ${formatDate(peaks.temperature.timestamp)}` : "Sin datos";
      dialog.querySelector("[data-peak-power]").textContent = peakText(peaks.power, 2, "kW");
      dialog.querySelector("[data-peak-power-meta]").textContent = peaks.power
        ? `${peaks.power.zone} · ${formatDate(peaks.power.timestamp)}` : "Sin datos";
      dialog.querySelector("[data-peak-energy]").textContent = peakText(peaks.energy, 3, "kWh");
      dialog.querySelector("[data-peak-energy-meta]").textContent = peaks.energy
        ? `${peaks.energy.zone} · ${formatDate(peaks.energy.timestamp)}` : "Sin datos";
      const samples = data.samples || [];
      drawChart(dialog.querySelector('[data-chart="temperature"]'), samples, "temperature_c", "#ffad42");
      drawChart(dialog.querySelector('[data-chart="power"]'), samples, "power_kw", "#42d9ff");

      const auditRows = dialog.querySelector("[data-audit-rows]");
      auditRows.replaceChildren();
      for (const audit of data.audit_logs || []) {
        const row = document.createElement("tr");
        addCell(row, formatDate(audit.timestamp));
        addCell(row, audit.action);
        addCell(row, audit.performed_by);
        addCell(row, JSON.stringify(audit.details || {}));
        auditRows.append(row);
      }
      setStatus(`${samples.length} muestras consultadas.`);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadErrors({ append = false } = {}) {
    setStatus("Consultando caja negra…");
    try {
      if (!append) errorOffset = 0;
      const data = await api(`/analytics/errors?limit=200&offset=${errorOffset}`);
      const rows = dialog.querySelector("[data-error-rows]");
      if (!append) rows.replaceChildren();
      for (const item of data.errors || []) {
        const row = document.createElement("tr");
        addCell(row, formatDate(item.timestamp));
        addCell(row, item.error_type);
        addCell(row, item.description);
        addCell(row, item.duration_ms == null ? "—" : `${item.duration_ms} ms`);
        rows.append(row);
      }
      errorOffset += data.errors?.length || 0;
      dialog.querySelector("[data-error-count]").textContent = `${data.total ?? 0} registro(s) · mostrando ${errorOffset}`;
      dialog.querySelector("[data-load-more-errors]").hidden = errorOffset >= Number(data.total || 0);
      setStatus("Caja negra actualizada.");
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function loadPins() {
    setStatus("Consultando PINs…");
    try {
      const [doors, pins] = await Promise.all([api("/pins/doors"), api("/pins?limit=200")]);
      const select = dialog.querySelector('[name="door_name"]');
      select.replaceChildren();
      for (const door of doors) {
        const option = document.createElement("option");
        option.value = door.door_name;
        option.textContent = door.door_name;
        select.append(option);
      }
      const rows = dialog.querySelector("[data-pin-rows]");
      rows.replaceChildren();
      for (const pin of pins) {
        const row = document.createElement("tr");
        addCell(row, pin.door_name);
        addCell(row, pin.pin_code);
        addCell(row, pin.target_user);
        addCell(row, pin.created_by);
        addCell(row, formatDate(pin.expires_at));
        const cell = document.createElement("td");
        const revoke = document.createElement("button");
        revoke.type = "button";
        revoke.textContent = "REVOCAR";
        revoke.disabled = !pin.is_active;
        revoke.addEventListener("click", () => revokePin(pin.id));
        cell.append(revoke);
        row.append(cell);
        rows.append(row);
      }
      setStatus(`${pins.length} PIN(s) activo(s).`);
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function revokePin(id) {
    try {
      await api(`/pins/${encodeURIComponent(id)}`, { method: "DELETE" });
      setStatus("PIN revocado.");
      await loadPins();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  dialog.querySelector("[data-admin-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => onClose?.());
  dialog.querySelectorAll("[data-tab]").forEach((tab) => tab.addEventListener("click", () => {
    const selected = tab.dataset.tab;
    dialog.querySelectorAll("[data-tab]").forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
    dialog.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== selected; });
    if (selected === "history") loadHistory();
    if (selected === "errors") loadErrors();
    if (selected === "pins") loadPins();
  }));
  dialog.querySelector("[data-refresh-history]").addEventListener("click", loadHistory);
  dialog.querySelector("[data-refresh-errors]").addEventListener("click", loadErrors);
  dialog.querySelector("[data-load-more-errors]").addEventListener("click", () => loadErrors({ append: true }));
  dialog.querySelector("[data-refresh-pins]").addEventListener("click", loadPins);
  dialog.querySelector("[data-days]").addEventListener("change", loadHistory);
  pinForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const durationHours = toDurationHours(form.get("duration_value"), form.get("duration_unit"));
      const generated = await api("/pins/generate", {
        method: "POST",
        body: JSON.stringify({
          door_name: String(form.get("door_name")),
          target_user: String(form.get("target_user")).trim(),
          duration_hours: durationHours,
        }),
      });
      const result = dialog.querySelector("[data-pin-result]");
      result.hidden = false;
      result.textContent = `PIN ${generated.pin_code} · ${generated.door_name} · vence ${formatDate(generated.expires_at)}`;
      setStatus("PIN creado; el código queda protegido en PostgreSQL.");
      event.currentTarget.reset();
      updateDurationLimit();
      await loadPins();
    } catch (error) {
      setStatus(error.message, true);
    }
  });

  loadHistory();
  return {
    open() { if (!dialog.open) dialog.showModal(); loadHistory(); },
    dispose() { dialog.close(); dialog.remove(); },
  };
}
