import { mountEventConsole } from "./event-console.js";
import { mountSecurityControls } from "./security-controls.js";

export function mountSidebarRight(root, options) {
  root.innerHTML = `<div id="event-console-root"></div><div id="security-controls-root"></div>`;
  const events = mountEventConsole(root.querySelector("#event-console-root"));
  const controls = mountSecurityControls(root.querySelector("#security-controls-root"), options);
  return {
    events,
    controls,
    checkSchedule: controls.checkSchedule,
    updateCamera: controls.updateCamera,
    setMode: controls.setMode,
    setConnection: events.setConnection,
    destroy: controls.destroy,
  };
}
