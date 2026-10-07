const PANEL_CONFIG = [
  {
    selector: "#sidebar-chat-root",
    title: "Asistente de seguridad",
    headings: [".chat-panel-heading"],
  },
  {
    selector: "#event-console-root",
    title: "Consola de eventos",
    headings: [".panel-heading"],
  },
  {
    selector: "#security-controls-root",
    title: "Control de seguridad y cierre de jornada",
    headings: [".security-panel .panel-heading", ".schedule-heading", ".selected-camera-panel .panel-heading"],
  },
];

export function mountPanelExpansion() {
  const mounted = [];
  for (const config of PANEL_CONFIG) {
    const root = document.querySelector(config.selector);
    if (!root) continue;

    const dialog = document.createElement("dialog");
    dialog.className = "expanded-panel-dialog";
    dialog.setAttribute("aria-label", config.title);
    dialog.innerHTML = `
      <header class="expanded-panel-heading">
        <h2>${config.title}</h2>
        <button class="icon-button" type="button" data-expanded-close aria-label="Cerrar ventana">×</button>
      </header>
      <div class="expanded-panel-content"></div>`;
    document.body.append(dialog);
    const content = dialog.querySelector(".expanded-panel-content");
    let returnParent = null;
    let returnBefore = null;
    let activeButton = null;

    function restorePanel() {
      if (returnParent?.isConnected) {
        returnParent.insertBefore(root, returnBefore?.parentNode === returnParent ? returnBefore : null);
      }
      returnParent = null;
      returnBefore = null;
      activeButton?.focus();
      activeButton = null;
    }

    const closeButton = dialog.querySelector("[data-expanded-close]");
    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", restorePanel);

    let hasHeading = false;
    for (const headingSelector of config.headings) {
      const heading = root.querySelector(headingSelector);
      if (!heading) continue;
      hasHeading = true;
      const expand = document.createElement("button");
      expand.className = "panel-expand-button";
      expand.type = "button";
      expand.setAttribute("aria-label", `Ampliar ${config.title}`);
      expand.title = "Abrir panel en ventana central";
      expand.textContent = "⛶";
      heading.append(expand);
      expand.addEventListener("click", () => {
        if (dialog.open) return;
        activeButton = expand;
        returnParent = root.parentNode;
        returnBefore = root.nextSibling;
        content.append(root);
        dialog.showModal();
      });
      mounted.push({ expand, dialog, root });
    }
    if (!hasHeading) dialog.remove();
  }

  return {
    dispose() {
      const dialogs = new Set(mounted.map(({ dialog }) => dialog));
      for (const dialog of dialogs) {
        if (dialog.open) dialog.close();
        dialog.remove();
      }
      for (const { expand } of mounted) expand.remove();
    },
  };
}
