import { formatValue } from "./history-data.js";

const dialog = document.querySelector("#history-dialog");
const canvas = document.querySelector("#history-chart");
const tableBody = document.querySelector("#history-table-body");
const currentDisplay = document.querySelector("#history-current-value");
const chartWrap = document.querySelector("#history-chart-wrap");
const tableWrap = document.querySelector("#history-table-wrap");
const emptyState = document.querySelector("#history-empty");
const ctx = canvas.getContext("2d");
let activeMetric = null;
let activeHistory = [];
let resizeObserver = null;

export function openHistory(metric) {
  activeMetric = { ...metric };
  activeHistory = metric.history.map((item) => ({ ...item, date: new Date(item.date) }));
  document.querySelector("#history-title").textContent = metric.title;
  tableBody.replaceChildren();
  emptyState.hidden = activeHistory.length > 0;
  chartWrap.hidden = activeHistory.length === 0;
  tableWrap.hidden = activeHistory.length === 0;
  if (!activeHistory.length) {
    emptyState.textContent = metric.connected
      ? "El modelo está conectado, pero todavía no hay lecturas para esta métrica."
      : "Modelo no conectado. El historial aparecerá cuando se reciban lecturas reales.";
  }
  document.querySelector("#history-summary-label").textContent = activeHistory.length
    ? `${activeHistory.length} LECTURAS RECIBIDAS · SOLO DATOS DEL MODELO`
    : "SIN LECTURAS RECIBIDAS";
  currentDisplay.textContent = activeHistory.length
    ? `${formatValue(activeHistory.at(-1).value, metric.digits)} ${metric.unit}`
    : "—";
  if (activeHistory.length) renderHistory();
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(drawChart);
  resizeObserver?.disconnect();
  if (activeHistory.length) {
    resizeObserver = new ResizeObserver(drawChart);
    resizeObserver.observe(canvas.parentElement);
  }
}

function renderHistory() {
  tableBody.replaceChildren();
  for (const item of [...activeHistory].reverse()) {
    const row = document.createElement("tr");
    const timeCell = document.createElement("td");
    const valueCell = document.createElement("td");
    timeCell.textContent = new Intl.DateTimeFormat("es", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(item.date);
    valueCell.textContent = `${formatValue(item.value, activeMetric.digits)} ${activeMetric.unit}`;
    row.append(timeCell, valueCell);
    tableBody.append(row);
  }
}

function drawChart() {
  if (!activeMetric || !dialog.open || !activeHistory.length) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const width = rect.width;
  const height = rect.height;
  const margin = { top: 12, right: 12, bottom: 24, left: 48 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = activeHistory.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const spread = maxValue - minValue || Math.max(Math.abs(maxValue) * 0.1, 1);
  const low = minValue - spread * 0.08;
  const high = maxValue + spread * 0.08;
  ctx.clearRect(0, 0, width, height);
  ctx.font = '9px "IBM Plex Mono", monospace';
  ctx.lineWidth = 1;
  for (let gridIndex = 0; gridIndex <= 4; gridIndex += 1) {
    const y = margin.top + (plotHeight * gridIndex) / 4;
    ctx.strokeStyle = "rgba(101,114,134,.22)";
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(width - margin.right, y); ctx.stroke();
    const labelValue = high - ((high - low) * gridIndex) / 4;
    ctx.fillStyle = "#657286";
    ctx.textAlign = "right";
    ctx.fillText(formatValue(labelValue, activeMetric.digits), margin.left - 7, y + 3);
  }
  const slot = plotWidth / values.length;
  values.forEach((value, index) => {
    const barHeight = Math.max(2, ((value - low) / (high - low)) * plotHeight);
    const x = margin.left + index * slot + slot * 0.18;
    const y = margin.top + plotHeight - barHeight;
    ctx.fillStyle = index === values.length - 1 ? activeMetric.color : `${activeMetric.color}86`;
    ctx.fillRect(x, y, Math.max(2, slot * 0.64), barHeight);
  });
}

dialog.addEventListener("close", () => resizeObserver?.disconnect());
