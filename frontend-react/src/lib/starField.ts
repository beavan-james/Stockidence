import { PALETTE, ditherStop, hexRGB } from "@/lib/palette";

/**
 * A quiet sky behind every page but the home page's disc: single-pixel stars
 * and a scatter of soft gaussian ones, in the disc's palette and dither but
 * dimmer, twinkling slowly. Drawn on the CPU at art resolution into a
 * transparent canvas; everything unlit stays clear so the page's black shows.
 *
 * Every star is placed by a hash of its art pixel (or grid cell), so the sky is
 * the same on every load and stays put when the window grows.
 */

/** Wide screens get the disc's 3 px art pixel, narrow ones 2. Matches the disc. */
const WIDE = "(min-width: 900px)";

/** The sky only needs to breathe, not move: a slow beat keeps the CPU idle. */
const FPS = 8;

/** Share of art pixels holding a star at 3 px per art pixel. Finer grids scale
 *  it down so a phone shows as many stars per inch as a desktop. */
const STAR_DENSITY = 0.0024;

/** Soft stars: the sky is cut into cells this many CSS px square and each
 *  cell has this chance of holding one. */
const SPLAT_CELL = 160;
const SPLAT_CHANCE = 0.24;

/** Palette stop -> RGBA pixel, little-endian, stop 0 left transparent. */
const COLOURS = new Uint32Array(
  PALETTE.map((h, i) => {
    if (i === 0) return 0;
    const [r, g, b] = hexRGB(h).map((v) => Math.round(v * 255));
    return ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
  }),
);

/** Integer hash of an art pixel (or cell) to [0, 1). */
function hash(x: number, y: number, salt = 0): number {
  let h = Math.imul(x + 0x3c6ef372, 0x27d4eb2d) ^ Math.imul(y + 0x7f4a7c15, 0x165667b1) ^ Math.imul(salt + 1, 0x9e3779b1);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

interface Sky {
  w: number;
  h: number;
  /** Single-pixel stars: pixel index, resting light, twinkle speed and phase. */
  point: Int32Array;
  pointL: Float32Array;
  pointSpeed: Float32Array;
  pointPhase: Float32Array;
  /** Soft stars: peak light, pulse speed and phase, and the run of `pix`/`weight` each one covers. */
  splatPeak: Float32Array;
  splatSpeed: Float32Array;
  splatPhase: Float32Array;
  splatEnd: Int32Array;
  pix: Int32Array;
  weight: Float32Array;
  /** Every pixel a star can light, each once: the only pixels redrawn each beat. */
  lit: Int32Array;
}

/** One soft star's footprint: a dithered gaussian, sometimes with a short four-point glint. */
function splatFootprint(cx: number, cy: number, sigma: number, aspect: number, angle: number, glint: number) {
  const pts: [number, number, number][] = [];
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const reach = Math.ceil(Math.max(3 * sigma * aspect, glint * 4));
  for (let dy = -reach; dy <= reach; dy++) {
    for (let dx = -reach; dx <= reach; dx++) {
      const u = (dx * cos + dy * sin) / aspect;
      const v = -dx * sin + dy * cos;
      let w = Math.exp(-(u * u + v * v) / (2 * sigma * sigma));
      if (glint > 0) {
        if (dy === 0) w = Math.max(w, 0.85 * Math.exp(-Math.abs(dx) / glint));
        if (dx === 0) w = Math.max(w, 0.85 * Math.exp(-Math.abs(dy) / glint));
      }
      if (w > 0.04) pts.push([cx + dx, cy + dy, w]);
    }
  }
  return pts;
}

function buildSky(w: number, h: number, px: number): Sky {
  const point: number[] = [];
  const pointL: number[] = [];
  const pointSpeed: number[] = [];
  const pointPhase: number[] = [];
  const density = STAR_DENSITY * (px / 3) ** 2;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const r = hash(x, y);
      if (r >= density) continue;
      const k = hash(x, y, 1);
      point.push(y * w + x);
      // Mostly plum, a few reaching maroon: dimmer than the disc's own sky.
      pointL.push(0.055 + 0.16 * k * k);
      pointSpeed.push(0.3 + 1.4 * hash(x, y, 2));
      pointPhase.push(k * 60);
    }
  }

  const splatPeak: number[] = [];
  const splatSpeed: number[] = [];
  const splatPhase: number[] = [];
  const splatEnd: number[] = [];
  const pix: number[] = [];
  const weight: number[] = [];
  const cell = Math.round(SPLAT_CELL / px);
  for (let gy = 0; gy * cell < h; gy++) {
    for (let gx = 0; gx * cell < w; gx++) {
      if (hash(gx, gy, 10) >= SPLAT_CHANCE) continue;
      const cx = gx * cell + Math.floor(hash(gx, gy, 11) * cell);
      const cy = gy * cell + Math.floor(hash(gx, gy, 12) * cell);
      const k = hash(gx, gy, 13);
      const sigma = (0.8 + 1.3 * k) * (3 / px);
      const glint = sigma > 1.5 && hash(gx, gy, 14) < 0.35 ? 1.2 + 1.4 * hash(gx, gy, 15) : 0;
      const shape = splatFootprint(cx, cy, sigma, 1 + 0.5 * hash(gx, gy, 16), Math.PI * hash(gx, gy, 17), glint);
      for (const [x, y, wt] of shape) {
        if (x < 0 || y < 0 || x >= w || y >= h) continue;
        pix.push(y * w + x);
        weight.push(wt);
      }
      // Bigger stars burn a little brighter; none reach the disc's oranges.
      splatPeak.push(0.17 + 0.18 * k + 0.07 * hash(gx, gy, 18));
      splatSpeed.push(0.15 + 0.35 * hash(gx, gy, 19));
      splatPhase.push(hash(gx, gy, 20) * 60);
      splatEnd.push(pix.length);
    }
  }

  const lit = new Set<number>(point);
  for (const i of pix) lit.add(i);
  return {
    w,
    h,
    point: Int32Array.from(point),
    pointL: Float32Array.from(pointL),
    pointSpeed: Float32Array.from(pointSpeed),
    pointPhase: Float32Array.from(pointPhase),
    splatPeak: Float32Array.from(splatPeak),
    splatSpeed: Float32Array.from(splatSpeed),
    splatPhase: Float32Array.from(splatPhase),
    splatEnd: Int32Array.from(splatEnd),
    pix: Int32Array.from(pix),
    weight: Float32Array.from(weight),
    lit: Int32Array.from(lit),
  };
}

export class StarField {
  private ctx: CanvasRenderingContext2D | null;
  private wide = window.matchMedia(WIDE);
  private still = window.matchMedia("(prefers-reduced-motion: reduce)");
  private sky: Sky | null = null;
  private image: ImageData | null = null;
  private pixels: Uint32Array | null = null;
  private light = new Float32Array(0);
  private px = 0;
  private raf = 0;
  private lastDraw = -1e9;

  private canvas: HTMLCanvasElement;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    window.addEventListener("resize", this.resize);
    this.wide.addEventListener("change", this.resize);
    this.still.addEventListener("change", this.restart);
    this.resize();
    this.restart();
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    window.removeEventListener("resize", this.resize);
    this.wide.removeEventListener("change", this.resize);
    this.still.removeEventListener("change", this.restart);
  }

  private resize = () => {
    const ctx = this.ctx;
    if (!ctx) return;
    const px = this.wide.matches ? 3 : 2;
    // A window can briefly report no size while it opens.
    const w = Math.max(1, Math.ceil(window.innerWidth / px));
    // Only ever grows taller, so a phone's toolbar sliding away doesn't rebuild the sky.
    const h = Math.max(1, Math.ceil(window.innerHeight / px), px === this.px && this.sky?.w === w ? this.sky.h : 0);
    if (this.sky && this.sky.w === w && this.sky.h === h && this.px === px) return;
    this.px = px;
    this.canvas.width = w;
    this.canvas.height = h;
    this.canvas.style.width = `${w * px}px`;
    this.canvas.style.height = `${h * px}px`;
    this.sky = buildSky(w, h, px);
    this.image = ctx.createImageData(w, h);
    this.pixels = new Uint32Array(this.image.data.buffer);
    this.light = new Float32Array(w * h);
    this.draw(performance.now() / 1000);
  };

  private restart = () => {
    cancelAnimationFrame(this.raf);
    if (this.still.matches) {
      this.draw(0);
      return;
    }
    const tick = (now: number) => {
      if (now - this.lastDraw >= 1000 / FPS) this.draw(now / 1000);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  };

  private draw(t: number) {
    const { ctx, sky, image, pixels, light } = this;
    if (!ctx || !sky || !image || !pixels) return;
    this.lastDraw = t * 1000;
    const still = this.still.matches;
    for (let n = 0; n < sky.lit.length; n++) light[sky.lit[n]] = 0;

    for (let n = 0; n < sky.point.length; n++) {
      const tw = still ? 1 : 0.65 + 0.35 * Math.sin(t * sky.pointSpeed[n] + sky.pointPhase[n]);
      light[sky.point[n]] = sky.pointL[n] * tw;
    }
    let start = 0;
    for (let s = 0; s < sky.splatPeak.length; s++) {
      const pulse = still ? 1 : 0.85 + 0.15 * Math.sin(t * sky.splatSpeed[s] + sky.splatPhase[s]);
      const peak = sky.splatPeak[s] * pulse;
      for (let j = start; j < sky.splatEnd[s]; j++) {
        const i = sky.pix[j];
        light[i] = 1 - (1 - light[i]) * (1 - peak * sky.weight[j]);
      }
      start = sky.splatEnd[s];
    }

    for (let n = 0; n < sky.lit.length; n++) {
      const i = sky.lit[n];
      pixels[i] = COLOURS[ditherStop(light[i], i % sky.w, (i / sky.w) | 0)];
    }
    ctx.putImageData(image, 0, 0);
  }
}
