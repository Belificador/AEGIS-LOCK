const STORAGE_KEY = "aegis.dashboard.sidebar-widths.v2";
const LEFT_MIN = 280;
const RIGHT_MIN = 280;
const LEFT_MAX = 560;
const RIGHT_MAX = 520;
const CENTER_MIN = 380;
const HANDLE_WIDTH = 8;
const GRID_GAP = 14;

export function mountSidebarResize(grid) {
  const leftSidebar = grid.querySelector(".sidebar-left");
  const rightSidebar = grid.querySelector(".sidebar-right");
  if (!leftSidebar || !rightSidebar) return { destroy() {} };

  const leftHandle = createHandle("Ajustar ancho del panel lateral izquierdo");
  const rightHandle = createHandle("Ajustar ancho del panel lateral derecho");
  grid.insertBefore(leftHandle, leftSidebar.nextSibling);
  grid.insertBefore(rightHandle, rightSidebar);

  let widths = readWidths();
  applyWidths();
  const abort = new AbortController();

  function limits(side) {
    const maxWidth = side === "left" ? LEFT_MAX : RIGHT_MAX;
    const minWidth = side === "left" ? LEFT_MIN : RIGHT_MIN;
    const otherWidth = widths[side === "left" ? "right" : "left"] || (side === "left" ? RIGHT_MIN : LEFT_MIN);
    const available = grid.clientWidth - GRID_GAP * 6 - HANDLE_WIDTH * 2 - CENTER_MIN - otherWidth;
    return { min: minWidth, max: Math.max(minWidth, Math.min(maxWidth, available)) };
  }

  function applyWidths() {
    widths.left = clamp(widths.left, LEFT_MIN, limits("left").max);
    widths.right = clamp(widths.right, RIGHT_MIN, limits("right").max);
    grid.style.setProperty("--sidebar-left-width", `${widths.left}px`);
    grid.style.setProperty("--sidebar-right-width", `${widths.right}px`);
    updateHandle(leftHandle, widths.left, limits("left"));
    updateHandle(rightHandle, widths.right, limits("right"));
  }

  function updateHandle(handle, width, { min, max }) {
    handle.setAttribute("aria-valuemin", String(min));
    handle.setAttribute("aria-valuemax", String(max));
    handle.setAttribute("aria-valuenow", String(Math.round(width)));
  }

  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(widths)); } catch { /* Keep the current layout in this session. */ }
  }

  function resizeWithKeyboard(event, side, direction) {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const delta = (event.key === "ArrowRight" ? 1 : -1) * (event.shiftKey ? 32 : 12) * direction;
    const { min, max } = limits(side);
    widths[side] = clamp(widths[side] + delta, min, max);
    applyWidths();
    persist();
  }

  leftHandle.addEventListener("keydown", (event) => resizeWithKeyboard(event, "left", 1), { signal: abort.signal });
  rightHandle.addEventListener("keydown", (event) => resizeWithKeyboard(event, "right", -1), { signal: abort.signal });
  leftHandle.addEventListener("pointerdown", (event) => startDrag(event, "left", 1), { signal: abort.signal });
  rightHandle.addEventListener("pointerdown", (event) => startDrag(event, "right", -1), { signal: abort.signal });

  function startDrag(event, side, direction) {
    if (event.button !== 0) return;
    event.preventDefault();
    const target = event.currentTarget;
    const startX = event.clientX;
    const startWidth = widths[side];
    target.setPointerCapture(event.pointerId);
    const move = (pointerEvent) => {
      const { min, max } = limits(side);
      widths[side] = clamp(startWidth + (pointerEvent.clientX - startX) * direction, min, max);
      applyWidths();
    };
    const finish = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      target.removeEventListener("pointercancel", finish);
      persist();
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", finish, { once: true });
    target.addEventListener("pointercancel", finish, { once: true });
  }

  window.addEventListener("resize", applyWidths, { signal: abort.signal });
  return {
    destroy() {
      abort.abort();
      leftHandle.remove();
      rightHandle.remove();
      grid.style.removeProperty("--sidebar-left-width");
      grid.style.removeProperty("--sidebar-right-width");
    },
  };
}

function createHandle(label) {
  const handle = document.createElement("div");
  handle.className = "sidebar-resize-handle";
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-orientation", "vertical");
  handle.tabIndex = 0;
  handle.setAttribute("aria-label", label);
  return handle;
}

function readWidths() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    return {
      left: clamp(Number(stored?.left) || 380, LEFT_MIN, LEFT_MAX),
      right: clamp(Number(stored?.right) || 360, RIGHT_MIN, RIGHT_MAX),
    };
  } catch {
    return { left: 380, right: 360 };
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
