import { createCameraModal } from "./camera-modal.js";

export function mountViewport(root) {
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
  const cameraModal = createCameraModal();
  let visor = null;
  let destroyed = false;
  const pendingEvents = [];
  import("../../visor3D.js").then(({ Visor3D }) => {
    if (destroyed) return;
    visor = new Visor3D(root.querySelector("#visor3d-container"), {
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

    if (String(event.tipo_evento).toLowerCase() === "camera_selected") openCameraFeed(event);
  }

  function openCameraFeed(event) {
    const metadata = event.metadata || {};
    const camera = metadata.camera && typeof metadata.camera === "object" ? metadata.camera : {};
    const id = metadata.camera_id || metadata.cameraId || camera.id || event.valor?.camera_id || event.valor || "EXT";
    const feed = metadata.feed_url || metadata.stream_url || metadata.video_url || metadata.camera_feed_url || metadata.video_feed || metadata.feed || metadata.url || metadata.ruta_feed || metadata.ruta_video || metadata.ruta || camera.feed_url || camera.url;
    cameraModal.open({
      id: String(id),
      shortName: metadata.name || metadata.nombre || camera.name || event.zona || "SELECCIONADA",
      location: metadata.location || metadata.ubicacion || camera.location || event.zona || "Ubicación recibida del emisor",
    }, typeof feed === "string" ? feed : undefined);
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

  setConnection(false);
  return {
    setConnection,
    update,
    setIntrusionAlert,
    destroy() {
      destroyed = true;
      window.clearTimeout(intrusionTimer);
      cameraModal.dispose();
      visor?.destroy();
    },
  };
}
