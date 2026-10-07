export function mountViewport(root, { onCameraSelected } = {}) {
  root.innerHTML = `
    <section class="viewport-panel" aria-labelledby="twin-title">
      <header class="viewport-heading">
        <div class="viewport-title"><span class="viewport-kicker">AEGIS / HOLOGRAPHIC VIEWPORT</span><h2 id="twin-title">GEMELO DIGITAL · OFICINA</h2><p>MODELO 3D Y TELEMETRÍA EN TIEMPO REAL</p></div>
        <span id="viewport-status" class="viewport-tag"><i class="status-led led-offline"></i> DESCONECTADO</span>
      </header>
      <div class="blueprint-stage twin-signal-stage" id="twin-stage" aria-busy="true">
        <div id="visor3d-container" class="visor3d-container" aria-label="Visor tridimensional del edificio"></div>
        <div class="stage-coordinate stage-coordinate-top" aria-hidden="true">GRID 04 <span>·</span> NODE AEG-01</div>
        <div class="radar-display" aria-hidden="true"><span class="radar-ring radar-ring-outer"></span><span class="radar-ring radar-ring-middle"></span><span class="radar-ring radar-ring-inner"></span><span class="radar-crosshair radar-crosshair-x"></span><span class="radar-crosshair radar-crosshair-y"></span><span class="radar-sweep"></span><span class="radar-origin"></span></div>
        <div class="stage-coordinate stage-coordinate-bottom" aria-hidden="true">LIVE FEED <span id="signal-zone">ESPERANDO DATOS</span><b id="signal-kind">SIN TELEMETRÍA</b></div>
        <div id="model-disconnected" class="model-state-panel" aria-live="polite">
          <span class="model-state-orb" aria-hidden="true"><i></i><b></b><em></em></span>
          <span class="model-state-overline"><i class="status-led led-warning"></i> CARGANDO MODELO 3D</span>
          <strong>PREPARANDO VISOR</strong>
          <p>El gemelo digital se está cargando desde models_3d/oficina.</p>
          <span class="model-state-foot"><i></i> MODELO LOCAL <b>·</b> CANAL DE TELEMETRÍA</span>
        </div>
        <div id="model-load-error" class="model-state-panel" hidden aria-live="polite">
          <span class="model-state-overline"><i class="status-led led-offline"></i> MODELO 3D NO DISPONIBLE</span>
          <strong>NO SE PUDO CARGAR EL EDIFICIO</strong>
          <p>Verifica que models_3d/oficina/edificio.glb esté disponible en el despliegue.</p>
        </div>
        <div id="emergency-mode-overlay" class="emergency-mode-overlay" hidden role="status" aria-live="assertive"><strong id="emergency-mode-title"></strong><span>AEGIS LOCK · PROTOCOLO ACTIVO</span></div>
        <div id="signal-hud" class="signal-hud" hidden><span id="signal-type"></span><time id="signal-timestamp"></time></div>
      </div>
      <footer class="viewport-foot"><span id="signal-footer"><i class="status-led led-offline"></i> DESCONECTADO DE RENDER</span><span>ARRASTRA PARA ROTAR · RUEDA PARA ZOOM</span></footer>
    </section>`;

  const stage = root.querySelector("#twin-stage");
  const loading = root.querySelector("#model-disconnected");
  const loadError = root.querySelector("#model-load-error");
  const status = root.querySelector("#viewport-status");
  const footer = root.querySelector("#signal-footer");
  const signalHud = root.querySelector("#signal-hud");
  const signalType = root.querySelector("#signal-type");
  const timestamp = root.querySelector("#signal-timestamp");
  const emergencyOverlay = root.querySelector("#emergency-mode-overlay");
  const emergencyTitle = root.querySelector("#emergency-mode-title");
  let visor = null;
  let destroyed = false;
  const pendingEvents = [];
  import("../../visor3D.js").then(({ Visor3D }) => {
    if (destroyed) return;
    visor = new Visor3D(root.querySelector("#visor3d-container"), {
      onCameraSelected,
      onLoad() {
        loading.hidden = true;
        stage.setAttribute("aria-busy", "false");
      },
      onError() {
        loading.hidden = true;
        loadError.hidden = false;
        stage.setAttribute("aria-busy", "false");
      },
    });
    pendingEvents.splice(0).forEach((event) => visor.update(event));
  }).catch((error) => {
    console.error("No se pudo inicializar el visor Three.js", error);
    loading.hidden = true;
    loadError.hidden = false;
    stage.setAttribute("aria-busy", "false");
  });
  let intrusionTimer = null;

  function setConnection(isConnected) {
    status.innerHTML = `<i class="status-led ${isConnected ? "led-normal" : "led-offline"}"></i> ${isConnected ? "🟢 CONECTADO A RENDER" : "🔴 DESCONECTADO"}`;
    footer.innerHTML = `<i class="status-led ${isConnected ? "led-normal" : "led-offline"}"></i> ${isConnected ? "ESCUCHANDO TELEMETRÍA" : "DESCONECTADO DE RENDER"}`;
  }

  function update(event) {
    if (visor) visor.update(event);
    else pendingEvents.push(event);
    signalHud.hidden = false;
    const zone = event.zone || event.zona || "GLOBAL";
    root.querySelector("#signal-zone").textContent = zone;
    root.querySelector("#signal-kind").textContent = String(event.tipo_evento || "TELEMETRÍA").toUpperCase();
    signalType.textContent = `${String(event.tipo_evento || "EVENTO").toUpperCase()} · ${zone}`;
    const date = event.timestamp ? new Date(event.timestamp) : new Date();
    timestamp.textContent = Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("es", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);

  }

  function setIntrusionAlert(zone) {
    stage.classList.add("is-intrusion-alert");
    const zoneLabel = root.querySelector("#signal-zone");
    if (zone) zoneLabel.textContent = `INTRUSIÓN · ${zone}`;
    window.clearTimeout(intrusionTimer);
    intrusionTimer = window.setTimeout(() => stage.classList.remove("is-intrusion-alert"), 6000);
    const event = { tipo_evento: "acceso_pin", valor: "DENIED", zona: zone || "global" };
    if (visor) visor.setIntrusionAlert(zone);
    else pendingEvents.push(event);
  }

  function clearIntrusionAlert() {
    window.clearTimeout(intrusionTimer);
    intrusionTimer = null;
    stage.classList.remove("is-intrusion-alert");
  }

  function setMode(mode) {
    const active = ["LOCKDOWN", "CIERRE DE JORNADA", "EVACUACIÓN"].includes(mode);
    emergencyOverlay.hidden = !active;
    emergencyOverlay.dataset.mode = active ? mode : "NORMAL";
    emergencyTitle.textContent = mode === "EVACUACIÓN"
      ? "MODO DE EVACUACIÓN"
      : mode === "LOCKDOWN" || mode === "CIERRE DE JORNADA"
        ? "CERRADO COMPLETAMENTE"
        : "";
  }

  setConnection(false);
  return {
    setConnection,
    update,
    setMode,
    setIntrusionAlert,
    clearIntrusionAlert,
    destroy() {
      destroyed = true;
      clearIntrusionAlert();
      visor?.destroy();
    },
  };
}
