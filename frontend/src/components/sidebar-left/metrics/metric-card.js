import { openHistory } from "./history-dialog.js";
import { formatValue } from "./history-data.js";
import { createMetricVisual } from "./metric-visuals.js";

const MAX_STORED_READINGS = 500;
const HISTORY_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
let visualSequence = 0;

export function createMetricCard(root, config) {
  const history = loadHistory(config.historyKey);
  let current = history.at(-1)?.value ?? null;
  let currentUnit = config.unit;
  let connected = false;
  let hasLiveValue = false;
  let statusText = history.length ? "ÚLTIMA LECTURA · HISTORIAL LOCAL" : "MODELO NO CONECTADO";
  const visual = createMetricVisual(config, ++visualSequence);
  const card = document.createElement("button");
  card.type = "button";
  card.className = `metric-card ${config.className} is-disconnected`;
  card.setAttribute("aria-label", `${config.title}: ver lecturas recibidas`);
  card.innerHTML = `
    <div class="metric-card-top"><span class="metric-card-title"></span><span class="metric-card-symbol" aria-hidden="true">${config.symbol}</span></div>
    <div class="metric-card-main"><strong class="metric-value mono"></strong><span class="metric-unit"></span></div>
    <div class="metric-card-meta"><i class="status-led led-offline"></i><span></span></div>
    <div class="metric-card-foot"><span class="metric-reading-count">SIN LECTURAS</span><span class="metric-skeleton" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><span>VER HISTORIAL ↗</span></div>`;
  card.querySelector(".metric-card-title").textContent = config.title;
  card.querySelector(".metric-unit").textContent = currentUnit;
  card.querySelector(".metric-card-meta").insertAdjacentElement("afterend", visual.element);
  root.append(card);

  function render() {
    card.querySelector(".metric-value").textContent = formatValue(current, config.digits);
    card.querySelector(".metric-unit").textContent = currentUnit;
    card.querySelector(".metric-card-meta span").textContent = statusText;
    card.querySelector(".metric-skeleton").hidden = history.length > 0;
    card.querySelector(".metric-reading-count").textContent = history.length
      ? `${history.length} LECTURA${history.length === 1 ? "" : "S"}`
      : connected ? "ESPERANDO LECTURA" : "SIN SEÑAL";
    card.querySelector(".status-led").className = `status-led ${connected ? hasLiveValue ? "led-normal" : "led-warning" : "led-offline"}`;
    card.classList.toggle("is-disconnected", !connected);
    card.classList.toggle("has-history", history.length > 0);
    card.setAttribute("aria-label", `${config.title}: ${current == null ? "sin lecturas" : `${formatValue(current, config.digits)} ${currentUnit}`}; ${history.length} lecturas guardadas. Abrir historial.`);
    visual.render(history, current);
  }

  card.addEventListener("click", () => {
    openHistory({
      title: config.title,
      unit: currentUnit,
      color: config.color,
      digits: config.digits,
      history,
      connected,
    });
  });

  render();
  return {
    set(value, nextStatus, timestamp, unit = config.unit) {
      if (value == null || !Number.isFinite(Number(value))) return;
      current = Number(value);
      currentUnit = unit;
      statusText = nextStatus;
      const parsedDate = timestamp ? new Date(timestamp) : new Date();
      history.push({ date: Number.isNaN(parsedDate.getTime()) ? new Date() : parsedDate, value: current });
      pruneHistory(history);
      saveHistory(config.historyKey, history);
      connected = true;
      hasLiveValue = true;
      render();
    },
    setStatus(nextStatus, modelIsConnected) {
      connected = modelIsConnected;
      if (!modelIsConnected) hasLiveValue = false;
      statusText = !modelIsConnected && history.length ? "SIN ENLACE · HISTORIAL LOCAL" : nextStatus;
      render();
    },
    get value() { return current; },
    element: card,
  };
}

function loadHistory(key) {
  if (!key) return [];
  try {
    const cutoff = Date.now() - HISTORY_WINDOW_MS;
    const entries = JSON.parse(localStorage.getItem(key) || "[]");
    if (!Array.isArray(entries)) return [];
    return entries
      .map((entry) => ({ date: new Date(entry.date), value: Number(entry.value) }))
      .filter((entry) => !Number.isNaN(entry.date.getTime()) && Number.isFinite(entry.value) && entry.date.getTime() >= cutoff)
      .sort((left, right) => left.date.getTime() - right.date.getTime())
      .slice(-MAX_STORED_READINGS);
  } catch {
    return [];
  }
}

function pruneHistory(history) {
  const cutoff = Date.now() - HISTORY_WINDOW_MS;
  const retained = history
    .filter((entry) => entry.date.getTime() >= cutoff)
    .sort((left, right) => left.date.getTime() - right.date.getTime())
    .slice(-MAX_STORED_READINGS);
  history.splice(0, history.length, ...retained);
}

function saveHistory(key, history) {
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(history.map(({ date, value }) => ({ date: date.toISOString(), value }))));
  } catch {
    // The dashboard still renders the current session if browser storage is unavailable.
  }
}
