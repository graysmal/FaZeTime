// "Enrage" (Odyssey) background: a parchment pixel grid with slowly drifting dithered storm clouds, drawn on a
// canvas. Same module in apps/extension and apps/operator (the apps share no code); keep the two copies equal.
// Cheap by design: a coarse grid (one cell = `cell` CSS px), ~10 frames/s, paused while the page is hidden,
// and a single static frame under prefers-reduced-motion.

export interface PixelSkyOptions {
  /** Cell size in CSS pixels. */
  cell?: number;
  /** Frames per second while animating. */
  fps?: number;
  /** Drift speed multiplier. */
  speed?: number;
  /** Draw one frame and stop (reduced motion). */
  still?: boolean;
}

const PAPER_TOP = '#eee6d6';
const PAPER_BOTTOM = '#e2d8c5';
const INK = 'rgba(146, 146, 136, 0.42)';
const INK_DOT = 'rgba(146, 146, 136, 0.34)';

/** Stable per-cell jitter in [-1, 1], so cloud edges look hand-stitched rather than smooth. */
function jitter(x: number, y: number): number {
  let h = (x * 374761393 + y * 668265263) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return (((h ^ (h >>> 16)) >>> 0) / 4294967295) * 2 - 1;
}

/** Smooth cloud density in roughly [0, 1] at grid cell (x, y), time t (seconds). */
function density(x: number, y: number, t: number): number {
  const a = Math.sin(x * 0.085 + t * 0.32 + Math.sin(y * 0.05 + t * 0.18) * 2.1);
  const b = Math.sin(y * 0.11 - t * 0.23 + Math.sin(x * 0.04 - t * 0.14) * 2.4);
  const c = Math.sin((x + y) * 0.05 + t * 0.11);
  return 0.5 + 0.22 * a + 0.2 * b + 0.12 * c;
}

export function startPixelSky(canvas: HTMLCanvasElement, opts: PixelSkyOptions = {}): () => void {
  const cell = opts.cell ?? 10;
  const frameMs = 1000 / (opts.fps ?? 10);
  const speed = opts.speed ?? 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) return () => undefined;
  const view = canvas.ownerDocument.defaultView ?? window;
  let raf = 0;
  let last = 0;
  let stopped = false;
  const t0 = performance.now();

  const fit = () => {
    const dpr = Math.min(2, view.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  const draw = (now: number) => {
    fit();
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const t = ((now - t0) / 1000) * speed;
    const paper = ctx.createLinearGradient(0, 0, 0, h);
    paper.addColorStop(0, PAPER_TOP);
    paper.addColorStop(1, PAPER_BOTTOM);
    ctx.fillStyle = paper;
    ctx.fillRect(0, 0, w, h);
    const cols = Math.ceil(w / cell);
    const rows = Math.ceil(h / cell);
    const pad = Math.max(1, Math.round(cell * 0.12));
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const v = density(x, y, t) + jitter(x, y) * 0.05;
        const px = x * cell;
        const py = y * cell;
        if (v > 0.74) {
          ctx.fillStyle = INK; // solid cloud body
          ctx.fillRect(px, py, cell, cell);
        } else if (v > 0.6) {
          if ((x + y) % 2 === 0) {
            ctx.fillStyle = INK; // dithered cloud edge
            ctx.fillRect(px + pad, py + pad, cell - pad * 2, cell - pad * 2);
          }
        } else if (x % 3 === 0 && y % 3 === 0) {
          ctx.fillStyle = INK_DOT; // the sparse stitch grid of the open sky
          const s = Math.round(cell * 0.55);
          ctx.fillRect(px + (cell - s) / 2, py + (cell - s) / 2, s, s);
        }
      }
    }
  };

  const loop = (now: number) => {
    if (stopped) return;
    if (now - last >= frameMs && canvas.ownerDocument.visibilityState !== 'hidden') {
      last = now;
      draw(now);
    }
    raf = view.requestAnimationFrame(loop);
  };

  if (opts.still) draw(t0 + 40_000);
  else raf = view.requestAnimationFrame(loop);

  const onResize = () => draw(performance.now());
  view.addEventListener('resize', onResize);
  return () => {
    stopped = true;
    view.cancelAnimationFrame(raf);
    view.removeEventListener('resize', onResize);
  };
}
