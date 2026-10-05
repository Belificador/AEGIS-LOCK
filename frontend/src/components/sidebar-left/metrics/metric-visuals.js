import { formatValue } from "./history-data.js";

const SVG_NS = "http://www.w3.org/2000/svg";

export function createMetricVisual(config, id) {
  const element = document.createElement("div");
  element.className = `metric-visual metric-visual-${config.visual}`;

  if (config.visual === "occupancy") {
    element.innerHTML = `
      <div class="occupancy-summary">
        <div class="occupancy-donut" aria-hidden="true">
          <svg viewBox="0 0 88 88" focusable="false">
            <circle class="donut-track" cx="44" cy="44" r="35"></circle>
            <circle class="donut-progress" cx="44" cy="44" r="35"></circle>
          </svg>
          <div class="donut-center"><strong>—</strong><span>PERSONAS</span></div>
        </div>
        <div class="occupancy-legend"><span class="chart-section-label">AFORO RECIBIDO</span><strong class="occupancy-peak">—</strong><span class="occupancy-peak-label">PICO REGISTRADO</span><span class="occupancy-range">Sin lecturas disponibles</span></div>
      </div>
      <div class="occupancy-history">
        <div class="metric-chart-heading"><span>TENDENCIA POR DÍA</span><strong class="occupancy-history-label">ESPERANDO TELEMETRÍA</strong></div>
        <svg class="occupancy-history-chart" viewBox="0 0 240 64" role="img" aria-label="Historial diario de aforo recibido" preserveAspectRatio="none">
          <path class="chart-grid" d="M0 7H240 M0 21H240 M0 35H240 M0 49H240"></path>
          <g class="occupancy-history-bars"></g>
          <line class="occupancy-average" x1="0" x2="240" y1="48" y2="48" hidden></line>
          <g class="occupancy-history-dates"></g>
        </svg>
        <div class="occupancy-history-legend"><span><i></i> MEDIA DIARIA RECIBIDA</span><span class="occupancy-days-count">0 DÍAS</span></div>
      </div>`;
    return { element, render: renderOccupancy };
  }

  const gradientId = `metric-gradient-${id}`;
  const areaId = `metric-area-${id}`;
  element.innerHTML = `
    <div class="metric-chart-heading"><span>TENDENCIA DE SESIÓN</span><strong class="metric-peak">SIN MUESTRAS</strong></div>
    <svg class="metric-area-chart" viewBox="0 0 240 62" role="img" aria-label="Tendencia de telemetría recibida" preserveAspectRatio="none">
      <defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${config.color}" stop-opacity=".38"></stop><stop offset="95%" stop-color="${config.color}" stop-opacity="0"></stop></linearGradient><linearGradient id="${areaId}" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="${config.color}" stop-opacity=".65"></stop><stop offset="100%" stop-color="${config.color}" stop-opacity="1"></stop></linearGradient></defs>
      <path class="chart-grid" d="M0 8H240 M0 23H240 M0 38H240 M0 53H240 M20 0V62 M80 0V62 M140 0V62 M200 0V62"></path>
      <path class="metric-area-path" fill="url(#${gradientId})"></path>
      <path class="metric-line-path" stroke="url(#${areaId})"></path>
      <circle class="metric-peak-point" r="3.2"></circle><circle class="metric-current-point" r="2.6"></circle>
    </svg>
    <div class="metric-chart-state" aria-hidden="true"><i></i><span>ESPERANDO TELEMETRÍA REAL</span></div>`;

  return { element, render: renderArea };

  function renderArea(history) {
    const svg = element.querySelector(".metric-area-chart");
    const area = svg.querySelector(".metric-area-path");
    const line = svg.querySelector(".metric-line-path");
    const peakPoint = svg.querySelector(".metric-peak-point");
    const currentPoint = svg.querySelector(".metric-current-point");
    const samples = history.slice(-24);
    const count = samples.length;
    const state = element.querySelector(".metric-chart-state");
    const peakLabel = element.querySelector(".metric-peak");

    state.hidden = count >= 2;
    state.querySelector("span").textContent = count === 1 ? "RECIBIENDO HISTORIAL" : "ESPERANDO TELEMETRÍA REAL";
    peakLabel.textContent = count ? `PICO ${formatValue(Math.max(...samples.map((item) => item.value)), config.digits)} ${config.unit}` : "SIN MUESTRAS";
    if (!count) {
      area.setAttribute("d", "");
      line.setAttribute("d", "");
      peakPoint.setAttribute("opacity", "0");
      currentPoint.setAttribute("opacity", "0");
      svg.setAttribute("aria-label", "Sin muestras de telemetría recibidas");
      return;
    }

    const values = samples.map((item) => item.value);
    const lowValue = Math.min(...values);
    const highValue = Math.max(...values);
    const spread = highValue - lowValue || Math.max(Math.abs(highValue) * 0.08, 1);
    const low = lowValue - spread * 0.12;
    const high = highValue + spread * 0.12;
    const points = samples.map((sample, index) => ({
      x: count === 1 ? 228 : 8 + (index * 224) / (count - 1),
      y: 50 - ((sample.value - low) / (high - low)) * 40,
    }));
    const lineData = smoothPath(points);
    line.setAttribute("d", count > 1 ? lineData : "");
    area.setAttribute("d", count > 1 ? `${lineData} L ${points.at(-1).x} 58 L ${points[0].x} 58 Z` : "");
    const peakIndex = values.indexOf(Math.max(...values));
    setCircle(peakPoint, points[peakIndex]);
    setCircle(currentPoint, points.at(-1));
    svg.setAttribute("aria-label", `${count} lecturas recibidas de ${config.title.toLowerCase()}; pico de ${formatValue(Math.max(...values), config.digits)} ${config.unit}`);
  }

  function renderOccupancy(history, current) {
    const maxObserved = history.length ? Math.max(...history.map((item) => item.value)) : 0;
    const ratio = maxObserved > 0 && current != null ? Math.min(1, Math.max(0, current / maxObserved)) : 0;
    const circumference = 2 * Math.PI * 35;
    const progress = element.querySelector(".donut-progress");
    progress.setAttribute("stroke-dasharray", `${circumference} ${circumference}`);
    progress.setAttribute("stroke-dashoffset", String(circumference * (1 - ratio)));
    element.querySelector(".donut-center strong").textContent = current == null ? "—" : formatValue(current, 0);
    element.querySelector(".occupancy-peak").textContent = history.length ? formatValue(maxObserved, 0) : "—";
    element.querySelector(".occupancy-range").textContent = history.length
      ? `${history.length} LECTURA${history.length === 1 ? "" : "S"} · MÁXIMO OBSERVADO`
      : "Sin lecturas disponibles";

    const days = aggregateDays(history);
    const group = element.querySelector(".occupancy-history-bars");
    const dateLabels = element.querySelector(".occupancy-history-dates");
    const averageLine = element.querySelector(".occupancy-average");
    group.replaceChildren();
    dateLabels.replaceChildren();
    const maxDaily = Math.max(0, ...days.map((day) => day.average));
    const average = days.length ? days.reduce((sum, day) => sum + day.average, 0) / days.length : 0;
    const averageY = maxDaily > 0 ? 48 - (average / maxDaily) * 34 : 48;
    averageLine.setAttribute("y1", String(averageY));
    averageLine.setAttribute("y2", String(averageY));
    averageLine.hidden = days.length > 1;

    const slot = days.length ? 224 / days.length : 0;
    days.forEach((day, index) => {
      const height = maxDaily > 0 ? (day.average / maxDaily) * 32 : 0;
      const rect = document.createElementNS(SVG_NS, "rect");
      rect.setAttribute("class", `occupancy-bar${day.key === localDayKey(new Date()) ? " is-today" : ""}`);
      rect.setAttribute("x", String(8 + index * slot + slot * 0.25));
      rect.setAttribute("y", String(48 - height));
      rect.setAttribute("width", String(Math.max(4, slot * 0.5)));
      rect.setAttribute("height", String(height));
      rect.setAttribute("rx", "2");
      rect.setAttribute("aria-label", `${day.label}: promedio ${formatValue(day.average, 0)} personas`);
      group.append(rect);

      const dateText = document.createElementNS(SVG_NS, "text");
      dateText.setAttribute("class", "occupancy-date-label");
      dateText.setAttribute("x", String(8 + index * slot + slot / 2));
      dateText.setAttribute("y", "61");
      dateText.setAttribute("text-anchor", "middle");
      dateText.textContent = day.label;
      dateLabels.append(dateText);
    });

    const label = days.length
      ? `${days.length} DÍA${days.length === 1 ? "" : "S"} CON DATOS`
      : "ESPERANDO TELEMETRÍA";
    element.querySelector(".occupancy-history-label").textContent = label;
    element.querySelector(".occupancy-days-count").textContent = `${days.length} DÍA${days.length === 1 ? "" : "S"}`;
    element.querySelector(".occupancy-history-chart").setAttribute("aria-label", days.length
      ? `Aforo medio por día en ${days.length} día${days.length === 1 ? "" : "s"}, basado en telemetría recibida`
      : "Aún no hay historial diario de aforo recibido");
  }
}

function smoothPath(points) {
  if (points.length < 2) return "";
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[Math.max(0, index - 1)];
    const current = points[index];
    const next = points[index + 1];
    const following = points[Math.min(points.length - 1, index + 2)];
    const controlOne = { x: current.x + (next.x - previous.x) / 6, y: current.y + (next.y - previous.y) / 6 };
    const controlTwo = { x: next.x - (following.x - current.x) / 6, y: next.y - (following.y - current.y) / 6 };
    path += ` C ${controlOne.x} ${controlOne.y}, ${controlTwo.x} ${controlTwo.y}, ${next.x} ${next.y}`;
  }
  return path;
}

function setCircle(circle, point) {
  circle.setAttribute("cx", String(point.x));
  circle.setAttribute("cy", String(point.y));
  circle.setAttribute("opacity", "1");
}

function aggregateDays(history) {
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  const grouped = new Map();
  for (const sample of history) {
    const date = new Date(sample.date);
    if (Number.isNaN(date.getTime()) || date.getTime() < cutoff) continue;
    const key = localDayKey(date);
    const day = grouped.get(key) || { key, label: date.toLocaleDateString("es", { day: "2-digit", month: "2-digit" }), total: 0, count: 0 };
    day.total += sample.value;
    day.count += 1;
    grouped.set(key, day);
  }
  return [...grouped.values()].sort((left, right) => left.key.localeCompare(right.key)).map((day) => ({
    ...day,
    average: day.total / day.count,
  }));
}

function localDayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
