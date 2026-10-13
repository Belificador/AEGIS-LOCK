import { mountEventConsole } from "./event-console.js";
import { mountSecurityControls } from "./security-controls.js";

export function mountSidebarRight(root, options) {
  root.innerHTML = `<div class="sidebar-right-carousel" role="region" tabindex="0" aria-label="Bitácora, seguridad y cámaras. Desliza horizontalmente para ver más paneles."><div id="event-console-root"></div><div id="security-controls-root"></div></div>`;
  const events = mountEventConsole(root.querySelector("#event-console-root"));
  const controls = mountSecurityControls(root.querySelector("#security-controls-root"), options);
  return {
    events,
    controls,
    initialMode: controls.initialMode,
    checkSchedule: controls.checkSchedule,
    updateCamera: controls.updateCamera,
    setMode: controls.setMode,
    setCameraAvailability: controls.setCameraAvailability,
    setConnection: events.setConnection,
    destroy: controls.destroy,
  };
}
