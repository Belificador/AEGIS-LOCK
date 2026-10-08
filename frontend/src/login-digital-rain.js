const GLYPHS = Array.from("01AEGISアイウエオカキクケコサシスセソタチツテトナニヌネノ");
const COLOR = "#00F0FF";
const FONT_SIZE = 14;
const FRAME_INTERVAL_MS = 66;

export function mountLoginDigitalRain(canvas) {
  const context = canvas?.getContext?.("2d", { alpha: false });
  if (!canvas || !context) return { setActive() {}, destroy() {} };

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let active = false;
  let animationFrame = null;
  let lastFrameAt = 0;
  let width = 0;
  let height = 0;
  let columns = 0;
  let drops = [];
  let speeds = [];

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.25);
    width = bounds.width;
    height = bounds.height;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    columns = Math.max(1, Math.min(130, Math.ceil(width / FONT_SIZE)));
    drops = Array.from({ length: columns }, () => Math.random() * (height / FONT_SIZE));
    speeds = Array.from({ length: columns }, () => 0.12 + Math.random() * 0.28);
    paintBlack();
    if (active && reducedMotion.matches) paintStatic();
  }

  function paintBlack() {
    context.fillStyle = "#020609";
    context.fillRect(0, 0, width, height);
  }

  function paintStatic() {
    paintBlack();
    context.font = `${FONT_SIZE}px monospace`;
    context.textBaseline = "top";
    context.shadowColor = COLOR;
    context.shadowBlur = 3;
    for (let column = 0; column < columns; column += 5) {
      const rows = 2 + Math.floor(Math.random() * 4);
      const start = Math.random() * Math.max(1, height / FONT_SIZE - rows);
      for (let offset = 0; offset < rows; offset += 1) {
        context.fillStyle = `rgba(0,240,255,${0.12 + Math.random() * 0.18})`;
        context.fillText(GLYPHS[Math.floor(Math.random() * GLYPHS.length)], column * FONT_SIZE, (start + offset) * FONT_SIZE);
      }
    }
    context.shadowBlur = 0;
  }

  function animate(timestamp) {
    if (!active || reducedMotion.matches || document.hidden) return;
    animationFrame = window.requestAnimationFrame(animate);
    if (timestamp - lastFrameAt < FRAME_INTERVAL_MS) return;
    lastFrameAt = timestamp;

    context.fillStyle = "rgba(2,6,9,0.16)";
    context.fillRect(0, 0, width, height);
    context.font = `${FONT_SIZE}px monospace`;
    context.textBaseline = "top";
    context.shadowColor = COLOR;
    context.shadowBlur = 4;
    for (let column = 0; column < columns; column += 1) {
      const y = drops[column] * FONT_SIZE;
      context.fillStyle = Math.random() > 0.985 ? "rgba(195,253,255,0.9)" : "rgba(0,240,255,0.52)";
      context.fillText(GLYPHS[Math.floor(Math.random() * GLYPHS.length)], column * FONT_SIZE, y);
      drops[column] += speeds[column];
      if (y > height && Math.random() > 0.98) {
        drops[column] = -Math.random() * 12;
        speeds[column] = 0.12 + Math.random() * 0.28;
      }
    }
    context.shadowBlur = 0;
  }

  function stopAnimation() {
    if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  function startAnimation() {
    stopAnimation();
    if (!active) return;
    resize();
    if (reducedMotion.matches) {
      paintStatic();
      return;
    }
    lastFrameAt = 0;
    animationFrame = window.requestAnimationFrame(animate);
  }

  function setActive(nextActive) {
    active = Boolean(nextActive);
    canvas.hidden = !active;
    if (active) startAnimation();
    else {
      stopAnimation();
      paintBlack();
    }
  }

  const onVisibilityChange = () => {
    if (active && !document.hidden) startAnimation();
    else stopAnimation();
  };
  const onMotionChange = () => {
    if (active) startAnimation();
  };
  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", onVisibilityChange);
  reducedMotion.addEventListener?.("change", onMotionChange);

  return {
    setActive,
    destroy() {
      active = false;
      stopAnimation();
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      reducedMotion.removeEventListener?.("change", onMotionChange);
      canvas.hidden = true;
      paintBlack();
    },
  };
}
