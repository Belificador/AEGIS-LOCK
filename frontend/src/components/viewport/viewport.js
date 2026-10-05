export function mountViewport(root) {
  root.innerHTML = `
    <section class="viewport-panel" aria-labelledby="twin-title">
      <header class="viewport-heading">
        <div class="viewport-title"><span class="viewport-kicker">AEGIS / HOLOGRAPHIC VIEWPORT</span><h2 id="twin-title">CAPTURA DE SEÑAL DEL GEMELO</h2><p>VISOR Y PLANO HABILITADOS AL CONECTAR EL MODELO</p></div>
        <span id="viewport-status" class="viewport-tag"><i class="status-led led-offline"></i> MODELO NO CONECTADO</span>
      </header>
      <div class="blueprint-stage twin-signal-stage">
        <div class="stage-coordinate stage-coordinate-top" aria-hidden="true">GRID 04 <span>·</span> NODE AEG-01</div>
        <div class="radar-display" aria-hidden="true"><span class="radar-ring radar-ring-outer"></span><span class="radar-ring radar-ring-middle"></span><span class="radar-ring radar-ring-inner"></span><span class="radar-crosshair radar-crosshair-x"></span><span class="radar-crosshair radar-crosshair-y"></span><span class="radar-sweep"></span><span class="radar-origin"></span></div>
        <div class="stage-wireframe" aria-hidden="true"><span class="wireframe-node node-one"></span><span class="wireframe-node node-two"></span><span class="wireframe-node node-three"></span><span class="wireframe-node node-four"></span><span class="wireframe-link link-one"></span><span class="wireframe-link link-two"></span><span class="wireframe-link link-three"></span><span class="wireframe-link link-four"></span><span class="wireframe-link link-five"></span><span class="wireframe-link link-six"></span></div>
        <div class="stage-coordinate stage-coordinate-bottom" aria-hidden="true">LATENCY <span>— ms</span><b>NO TELEMETRY</b></div>
        <div id="model-disconnected" class="model-state-panel" aria-live="polite">
          <span class="model-state-orb" aria-hidden="true"><i></i><b></b><em></em></span>
          <span class="model-state-overline"><i class="status-led led-offline"></i> ENLACE EN ESPERA</span>
          <strong>MODELO NO CONECTADO</strong>
          <p>Esperando telemetría del gemelo digital.<br />Los datos aparecerán al recibir una señal válida.</p>
          <span class="model-state-foot"><i></i> ESPERANDO TELEMETRÍA <b>·</b> CANAL SEGURO</span>
        </div>
        <section id="model-connected" class="model-connected-panel" hidden aria-label="Última señal recibida">
          <div class="signal-heading"><span><i class="status-led led-normal"></i> SEÑAL RECIBIDA</span><time id="signal-timestamp"></time></div>
          <p id="signal-source" class="signal-source"></p>
          <pre id="signal-payload" class="signal-payload"></pre>
        </section>
      </div>
      <footer class="viewport-foot"><span id="signal-footer"><i class="status-led led-offline"></i> ESPERANDO CONEXIÓN</span><span>SOLO DATOS RECIBIDOS DEL MODELO</span></footer>
    </section>`;

  const disconnected = root.querySelector("#model-disconnected");
  const connected = root.querySelector("#model-connected");
  const status = root.querySelector("#viewport-status");
  const footer = root.querySelector("#signal-footer");
  const timestamp = root.querySelector("#signal-timestamp");
  const source = root.querySelector("#signal-source");
  const payload = root.querySelector("#signal-payload");

  function setConnection(isConnected) {
    disconnected.hidden = isConnected;
    connected.hidden = !isConnected;
    status.innerHTML = `<i class="status-led ${isConnected ? "led-normal" : "led-offline"}"></i> ${isConnected ? "SEÑAL RECIBIDA" : "MODELO NO CONECTADO"}`;
    footer.innerHTML = `<i class="status-led ${isConnected ? "led-normal" : "led-offline"}"></i> ${isConnected ? "CAPTURANDO TELEMETRÍA" : "ESPERANDO CONEXIÓN"}`;
    if (!isConnected) {
      source.textContent = "";
      timestamp.textContent = "";
      payload.textContent = "";
    }
  }

  function update(event) {
    disconnected.hidden = true;
    connected.hidden = false;
    status.innerHTML = '<i class="status-led led-normal"></i> SEÑAL RECIBIDA';
    footer.innerHTML = '<i class="status-led led-normal"></i> CAPTURANDO TELEMETRÍA';
    source.textContent = event.source_id ? `FUENTE · ${event.source_id}` : "SEÑAL RECIBIDA";
    const date = event.timestamp ? new Date(event.timestamp) : new Date();
    timestamp.textContent = Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("es", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);
    payload.textContent = JSON.stringify(event, null, 2);
  }

  setConnection(false);
  return { setConnection, update };
}
