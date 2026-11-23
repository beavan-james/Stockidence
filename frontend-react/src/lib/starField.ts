import { PALETTE, ditherStop, hexRGB } from "@/lib/palette";

/**
 * A quiet sky behind every page but the home page's disc: single-pixel stars
 * and a scatter of soft gaussian ones, in the disc's palette and dither but
 * dimmer, twinkling slowly. Drawn on the CPU at art resolution into a
 * transparent canvas; everything unlit stays clear so the page's black shows.
 *
 * Every star is placed by a hash of its art pixel (or grid cell), so the sky is
 * the same on every load and stays put when the window grows. Every so often
 * one star flares: a short burst of gaussian sparks that loops out and burns
 * back down to the quiet sky.
 */

/** Wide screens get the disc's 3 px art pixel, narrow ones 2. Matches the disc. */
const WIDE = "(min-width: 900px)";

/** The sky only needs to breathe, not move: a slow beat keeps the CPU idle. */
const FPS = 8;

/** Share of art pixels holding a star at 3 px per art pixel. Finer grids scale
 *  it down so a phone shows as many stars per inch as a desktop. */
const STAR_DENSITY = 0.0018;

/** Soft stars: the sky is cut into cells this many CSS px square and each
 *  cell has this chance of holding one. */
const SPLAT_CELL = 160;
const SPLAT_CHANCE = 0.16;

/** A flare every 30 to 60 s; the first comes sooner, so a short visit still sees one. */
const FLARE_EVERY: [number, number] = [30, 60];
const FIRST_FLARE: [number, number] = [8, 16];

/** How long a flare burns (s), and how often it redraws while it does. */
const FLARE_SECONDS = 3.6;
const FLARE_FPS = 20;

/** Sparks per flare, and how far from the star a flare can light, in units of 3 CSS px. */
const SPARK_COUNT = 44;
const FLARE_REACH = 46;

/** The page column (max-w-7xl) and the narrowest margin beside it, in CSS
 *  px, that a flare is put in instead of behind the text. */
const COLUMN = 1280;
const MARGIN_MIN = 120;

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
  /** Soft stars: centre, peak light, pulse speed and phase, and the run of `pix`/`weight` each one covers. */
  splatX: Float32Array;
  splatY: Float32Array;
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
      // The two darkest plums only: there to notice, not to read around.
      pointL.push(0.045 + 0.07 * k * k);
      pointSpeed.push(0.3 + 1.4 * hash(x, y, 2));
      pointPhase.push(k * 60);
    }
  }

  const splatX: number[] = [];
  const splatY: number[] = [];
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
      const sigma = (0.8 + 1.1 * k) * (3 / px);
      const glint = sigma > 1.4 && hash(gx, gy, 14) < 0.25 ? 1 + 0.8 * hash(gx, gy, 15) : 0;
      const shape = splatFootprint(cx, cy, sigma, 1 + 0.5 * hash(gx, gy, 16), Math.PI * hash(gx, gy, 17), glint);
      for (const [x, y, wt] of shape) {
        if (x < 0 || y < 0 || x >= w || y >= h) continue;
        pix.push(y * w + x);
        weight.push(wt);
      }
      splatX.push(cx);
      splatY.push(cy);
      // Plum halos round a maroon core at most: none reach the disc's rusts and oranges.
      splatPeak.push(0.15 + 0.07 * k + 0.04 * hash(gx, gy, 18));
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
    splatX: Float32Array.from(splatX),
    splatY: Float32Array.from(splatY),
    splatPeak: Float32Array.from(splatPeak),
    splatSpeed: Float32Array.from(splatSpeed),
    splatPhase: Float32Array.from(splatPhase),
    splatEnd: Int32Array.from(splatEnd),
    pix: Int32Array.from(pix),
    weight: Float32Array.from(weight),
    lit: Int32Array.from(lit),
  };
}

/** Spark fields, per spark: start angle, curl, reach, launch delay, life, light, size, and whether it falls back. */
const SPARK = 8;

interface Flare {
  start: number;
  /** Centre, in art px, and the art px per design unit (1 unit = 3 CSS px). */
  cx: number;
  cy: number;
  unit: number;
  /** The art-pixel rectangle it can light, and its light there. */
  x0: number;
  y0: number;
  w: number;
  h: number;
  light: Float32Array;
  sparks: Float32Array;
}

const rand = (a: number, b: number) => a + (b - a) * Math.random();
const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** Screen-blend `v` into `buf[i]`, so overlapping light brightens without clipping. */
function screen(buf: Float32Array, i: number, v: number) {
  buf[i] = 1 - (1 - buf[i]) * (1 - v);
}

/**
 * Where the next flare goes, in CSS px: in the margin beside the page column
 * when there's room for one, so it erupts beside the text, not behind it;
 * otherwise anywhere below the header. Prefers a soft star already there.
 */
function flareSite(sky: Sky, px: number): [number, number] {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = vw >= 1024 ? 48 : vw >= 640 ? 24 : 16;
  const margin = (vw - Math.min(vw, COLUMN)) / 2 + pad;
  const top = 64 + 70;
  const bottom = Math.max(top + 1, vh - 70);
  const inside = (x: number, y: number) =>
    y >= top &&
    y <= bottom &&
    (margin >= MARGIN_MIN
      ? (x >= 0.2 * margin && x <= 0.8 * margin) || (x >= vw - 0.8 * margin && x <= vw - 0.2 * margin)
      : x >= 0.1 * vw && x <= 0.9 * vw);
  const stars: [number, number][] = [];
  for (let s = 0; s < sky.splatX.length; s++) {
    const x = (sky.splatX[s] + 0.5) * px;
    const y = (sky.splatY[s] + 0.5) * px;
    if (inside(x, y)) stars.push([x, y]);
  }
  if (stars.length) return stars[Math.floor(Math.random() * stars.length)];
  const y = rand(top, bottom);
  if (margin < MARGIN_MIN) return [rand(0.1, 0.9) * vw, y];
  const x = rand(0.2, 0.8) * margin;
  return [Math.random() < 0.5 ? x : vw - x, y];
}

function makeFlare(sky: Sky, px: number, start: number): Flare {
  const [sx, sy] = flareSite(sky, px);
  const cx = Math.floor(sx / px);
  const cy = Math.floor(sy / px);
  // Phones have no margin to put it in, so there it burns smaller over the text.
  const unit = (3 / px) * (px === 3 ? 1 : 0.75);
  const r = Math.ceil(FLARE_REACH * unit);
  const x0 = Math.max(0, cx - r);
  const y0 = Math.max(0, cy - r);
  const w = Math.min(sky.w, cx + r + 1) - x0;
  const h = Math.min(sky.h, cy + r + 1) - y0;

  // Most sparks erupt to one side and loop back down onto the star, like a
  // prominence; the rest are thrown clear in every direction.
  const side = rand(0, 2 * Math.PI);
  const sparks = new Float32Array(SPARK_COUNT * SPARK);
  for (let n = 0; n < SPARK_COUNT; n++) {
    const loop = Math.random() < 0.7;
    sparks.set(
      [
        loop ? side + rand(-1.1, 1.1) : rand(0, 2 * Math.PI),
        loop ? rand(-1.3, 1.3) : rand(-0.3, 0.3),
        loop ? rand(8, 24) : rand(14, 34),
        rand(0.05, 0.9),
        rand(1.1, 2.3),
        rand(0.4, 0.62),
        rand(0.7, 1.15),
        loop ? 1 : 0,
      ],
      n * SPARK,
    );
  }
  return { start, cx, cy, unit, x0, y0, w, h, light: new Float32Array(w * h), sparks };
}

/** A gaussian splat of light `v` and size `sigma` (art px) at (x, y), clipped to the flare's rectangle. */
function splatInto(f: Flare, x: number, y: number, sigma: number, v: number) {
  const reach = Math.ceil(2.5 * sigma);
  const ix = Math.round(x);
  const iy = Math.round(y);
  for (let py = Math.max(f.y0, iy - reach); py <= Math.min(f.y0 + f.h - 1, iy + reach); py++) {
    for (let qx = Math.max(f.x0, ix - reach); qx <= Math.min(f.x0 + f.w - 1, ix + reach); qx++) {
      const dx = qx - x;
      const dy = py - y;
      const g = Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
      if (g > 0.03) screen(f.light, (py - f.y0) * f.w + (qx - f.x0), v * g);
    }
  }
}

/**
 * The flare's light at time `t` (s). Over FLARE_SECONDS the star flashes
 * gold with a four-point glint, a faint ring runs out from it, and sparks loop
 * out and fall back, cooling through the palette from orange to plum as they
 * go. Returns false once it has burnt out.
 */
function paintFlare(f: Flare, t: number): boolean {
  const age = t - f.start;
  const u = age / FLARE_SECONDS;
  f.light.fill(0);
  if (u >= 1) return false;
  const { unit, cx, cy } = f;

  // The star: a sharp rise, a brief flash, then a long cool-down.
  const env = smooth(0, 0.07, u) * (1 - smooth(0.12, 0.8, u));
  const flash = Math.exp(-(((u - 0.09) / 0.045) ** 2));
  const core = Math.min(0.85, 0.62 * env + 0.2 * flash);
  const coreSigma = 1.3 * unit;
  const haloSigma = 4.5 * unit;
  const arm = (3 + 13 * env + 6 * flash) * unit;
  // The ring leaves with the flash and fades well inside the flare's reach.
  const ru = Math.max(0, (u - 0.06) / 0.5);
  const ring = (3 + 30 * (1 - (1 - Math.min(1, ru)) ** 3)) * unit;
  const ringLight = u < 0.06 ? 0 : 0.13 * (1 - smooth(0, 1, ru));
  const ringWidth = 1.3 * unit;

  for (let y = 0; y < f.h; y++) {
    const dy = f.y0 + y - cy;
    for (let x = 0; x < f.w; x++) {
      const dx = f.x0 + x - cx;
      const d2 = dx * dx + dy * dy;
      let v = core * Math.exp(-d2 / (2 * coreSigma * coreSigma));
      v = 1 - (1 - v) * (1 - 0.22 * env * Math.exp(-d2 / (2 * haloSigma * haloSigma)));
      if (dy === 0) v = Math.max(v, 0.6 * env * Math.exp(-Math.abs(dx) / arm));
      if (dx === 0) v = Math.max(v, 0.6 * env * Math.exp(-Math.abs(dy) / (arm * 0.7)));
      if (ringLight > 0.01) {
        const off = (Math.sqrt(d2) - ring) / ringWidth;
        v = 1 - (1 - v) * (1 - ringLight * Math.exp(-off * off));
      }
      f.light[y * f.w + x] = v;
    }
  }

  // Sparks, each drawn with a dimmer copy a moment behind it as a short trail.
  const s = f.sparks;
  for (let n = 0; n < SPARK_COUNT; n++) {
    const o = n * SPARK;
    const life = s[o + 4];
    for (const [lag, share] of [
      [0, 1],
      [0.07, 0.45],
    ]) {
      const tau = age - s[o + 3] - lag;
      if (tau <= 0 || tau >= life) continue;
      const p = tau / life;
      // A loop goes out and comes back; the rest decelerate to a stop.
      const r = s[o + 2] * (s[o + 7] ? Math.sin(Math.PI * p) : 1 - Math.exp(-4 * p)) * unit;
      const a = s[o] + s[o + 1] * p;
      const v = s[o + 5] * share * (1 - p) ** 1.4 * smooth(0, 0.06, p);
      splatInto(f, cx + r * Math.cos(a), cy + r * Math.sin(a), s[o + 6] * unit, v);
    }
  }
  return true;
}

export class StarField {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D | null;
  private wide = window.matchMedia(WIDE);
  private still = window.matchMedia("(prefers-reduced-motion: reduce)");
  private sky: Sky | null = null;
  private image: ImageData | null = null;
  private pixels: Uint32Array | null = null;
  private light = new Float32Array(0);
  private px = 0;
  private raf = 0;
  private lastSky = -1e9;
  private lastFlare = -1e9;
  private lastFrame = 0;
  private flare: Flare | null = null;
  /** When the next flare starts, in seconds of page time; 0 = none (reduced motion). */
  private nextFlare = 0;

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
    // A flare drawn on the old grid would land in the wrong place; let it go.
    this.flare = null;
    this.twinkle(performance.now() / 1000);
    ctx.putImageData(this.image, 0, 0);
  };

  private restart = () => {
    cancelAnimationFrame(this.raf);
    this.flare = null;
    const now = performance.now();
    if (this.still.matches) {
      this.nextFlare = 0;
      this.twinkle(0);
      if (this.image) this.ctx?.putImageData(this.image, 0, 0);
      return;
    }
    this.nextFlare = now / 1000 + rand(...FIRST_FLARE);
    this.lastFrame = now;
    const tick = (time: number) => {
      this.raf = requestAnimationFrame(tick);
      this.frame(time);
    };
    this.raf = requestAnimationFrame(tick);
  };

  private frame(now: number) {
    const { ctx, sky, image } = this;
    if (!ctx || !sky || !image) return;
    const t = now / 1000;
    // Back from a hidden tab: don't spend the whole wait at once on a flare.
    if (now - this.lastFrame > 1000) {
      this.flare = null;
      this.nextFlare = Math.max(this.nextFlare, t + rand(...FIRST_FLARE));
    }
    this.lastFrame = now;
    if (!this.flare && this.nextFlare > 0 && t >= this.nextFlare) {
      this.flare = makeFlare(sky, this.px, t);
      this.nextFlare = t + FLARE_SECONDS + rand(...FLARE_EVERY);
    }

    const skyDue = now - this.lastSky >= 1000 / FPS;
    const flare = this.flare;
    const flareDue = flare !== null && now - this.lastFlare >= 1000 / FLARE_FPS;
    if (!skyDue && !flareDue) return;
    if (skyDue) {
      this.lastSky = now;
      this.twinkle(t);
    }
    if (flare) {
      this.lastFlare = now;
      const burning = paintFlare(flare, t);
      this.resolveFlare(flare);
      if (!burning) this.flare = null;
      if (!skyDue) ctx.putImageData(image, 0, 0, flare.x0, flare.y0, flare.w, flare.h);
    }
    if (skyDue) ctx.putImageData(image, 0, 0);
  }

  /** The stars' light at time `t` (s), resolved to palette colours. */
  private twinkle(t: number) {
    const { sky, pixels, light } = this;
    if (!sky || !pixels) return;
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
    // The beat just repainted any star under a running flare without it.
    if (this.flare) this.resolveFlare(this.flare);
  }

  /** Repaint the flare's rectangle: the stars there, with the flare's light over them. */
  private resolveFlare(f: Flare) {
    const { sky, pixels, light } = this;
    if (!sky || !pixels) return;
    for (let y = 0; y < f.h; y++) {
      const ay = f.y0 + y;
      for (let x = 0; x < f.w; x++) {
        const ax = f.x0 + x;
        const i = ay * sky.w + ax;
        const v = 1 - (1 - light[i]) * (1 - f.light[y * f.w + x]);
        pixels[i] = COLOURS[ditherStop(v, ax, ay)];
      }
    }
  }
}
