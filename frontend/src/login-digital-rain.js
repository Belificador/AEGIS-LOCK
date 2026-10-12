const GLYPHS = Array.from("01AEGISアイウエオカキクケコサシスセソタチツテトナニヌネノ");
const FONT_SIZE = 15;
const FRAME_INTERVAL_MS = 48;

export function mountLoginDigitalRain(canvas) {
  const context = canvas?.getContext?.("2d", { alpha: false });
  if (!canvas || !context) return { setActive() {}, destroy() {} };

  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let active = false;
  let frame = 0;
  let lastFrame = 0;
  let width = 0;
  let height = 0;
  let pixelRatio = 1;
  let drops = [];
  let speeds = [];

  function configureCanvas() {
    if (!active) return;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
    width = bounds.width;
    height = bounds.height;
    canvas.width = Math.round(width * pixelRatio);
    canvas.height = Math.round(height * pixelRatio);
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    const columns = Math.max(1, Math.ceil(width / FONT_SIZE));
    drops = Array.from({ length: columns }, () => Math.random() * (height / FONT_SIZE));
    speeds = Array.from({ length: columns }, () => 0.55 + Math.random() * 0.75);
    drawBackground();
    if (reducedMotion?.matches) drawStillFrame();
  }

  function drawBackground() {
    context.fillStyle = "#00050A";
    context.fillRect(0, 0, width, height);
  }

  function drawStillFrame() {
    context.font = `${FONT_SIZE}px monospace`;
    context.textBaseline = "top";
    for (let column = 0; column < drops.length; column += 5) {
      const length = 2 + Math.floor(Math.random() * 4);
      const start = Math.random() * Math.max(1, height / FONT_SIZE - length);
      for (let offset = 0; offset < length; offset += 1) {
        context.fillStyle = `rgba(0,240,255,${0.14 + Math.random() * 0.22})`;
        context.fillText(
          GLYPHS[Math.floor(Math.random() * GLYPHS.length)],
          column * FONT_SIZE,
          (start + offset) * FONT_SIZE,
        );
      }
    }
  }

  function animate(timestamp) {
    if (!active || document.hidden || reducedMotion?.matches) {
      frame = 0;
      return;
    }
    frame = window.requestAnimationFrame(animate);
    if (timestamp - lastFrame < FRAME_INTERVAL_MS) return;
    lastFrame = timestamp;
    context.fillStyle = "rgba(0,5,10,0.17)";
    context.fillRect(0, 0, width, height);
    context.font = `${FONT_SIZE}px monospace`;
    context.textBaseline = "top";

    for (let column = 0; column < drops.length; column += 1) {
      const y = drops[column] * FONT_SIZE;
      context.fillStyle = Math.random() > 0.985 ? "#B7FAFF" : "rgba(0,240,255,0.75)";
      context.fillText(GLYPHS[Math.floor(Math.random() * GLYPHS.length)], column * FONT_SIZE, y);
      drops[column] += speeds[column];
      if (y > height && Math.random() > 0.975) {
        drops[column] = -Math.random() * 18;
        speeds[column] = 0.55 + Math.random() * 0.75;
      }
    }
  }

  function stopAnimation() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
  }

  function startAnimation() {
    if (!active || document.hidden || reducedMotion?.matches || frame) return;
    lastFrame = 0;
    frame = window.requestAnimationFrame(animate);
  }

  function setActive(nextActive) {
    active = Boolean(nextActive);
    canvas.hidden = !active;
    if (!active) {
      stopAnimation();
      return;
    }
    configureCanvas();
    startAnimation();
  }

  const onVisibilityChange = () => active && (document.hidden ? stopAnimation() : startAnimation());
  const onMotionChange = () => {
    if (!active) return;
    stopAnimation();
    configureCanvas();
    startAnimation();
  };

  window.addEventListener("resize", configureCanvas);
  document.addEventListener("visibilitychange", onVisibilityChange);
  reducedMotion?.addEventListener?.("change", onMotionChange);

  return {
    setActive,
    destroy() {
      active = false;
      stopAnimation();
      window.removeEventListener("resize", configureCanvas);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      reducedMotion?.removeEventListener?.("change", onMotionChange);
      canvas.hidden = true;
      drawBackground();
    },
  };
}
