/**
 * The home page's disc: every ranked stock as a cloud of gaussian splats on a
 * lit disc, resolved to chunky art pixels on a fixed palette.
 *
 * A stock's rank sets its orbit (the top of the list sits on the bright inner
 * rim) and its sector sets the wedge of the disc it orbits in. The disc
 * material between stocks takes the colour of the ranks at its radius, so the
 * fade from gold to umber is the ranking itself.
 *
 * Two WebGL2 passes:
 *  1. Instanced quads fitted to each splat's projected 2D covariance (3 sigma),
 *     screen-blended into an offscreen picture at twice the art resolution.
 *  2. A fullscreen resolve: average each art pixel's 2 x 2 samples, take the
 *     luminance, and choose between the two palette stops either side of it
 *     with a fixed 4 x 4 Bayer threshold. The canvas holds only art pixels;
 *     CSS (.pixelated) enlarges them without smoothing.
 */

import { LUMA_CUT, PALETTE, STOP_LUMA, hexRGB } from "@/lib/palette";

export interface DiscStock {
  ticker: string;
  rank: number;
  sector: string | null;
}

interface DiscCallbacks {
  /** The stock the label should show changed (-1 = none). */
  onShow: (index: number) => void;
}

/** Light each fifth gives off before the palette resolve (brighter = more favoured). */
const GLOW_HEX = ["#ffc46b", "#ff8d00", "#d2601c", "#8c4421", "#4a2a17"];

/** A low, slightly rolled view of a flat disc. */
const CAM = { dist: 2.4, tilt: 0.36, roll: 0.1 };

/** Screen pixels per art pixel; narrow screens get one step finer so the disc keeps its rings. */
const PIXEL = 3;

/** Floats per splat: position 3, colour 3, alpha, sigma, aspect, phase, orbit radius, stock id. */
const STRIDE = 12;

/** How near a stock's centre, in CSS px, the pointer must be to name it. Wide
 *  enough that almost anywhere on the disc names its nearest stock. */
const PICK_RADIUS = 44;

/** The centre star stands for the top of the list: pointing within this many
 *  CSS px of it names the #1 stock. */
const STAR_RADIUS = 30;

/** The stock already named keeps its label until another is this many times
 *  nearer, so the label doesn't flicker between neighbours as the disc turns. */
const PICK_STICKY = 1.25;

/** Wide layout: the disc sits right of the copy and fades under it. Matches the CSS breakpoint. */
const WIDE = "(min-width: 900px)";

/** Seeded (mulberry32), so every load draws the same disc. */
function seeded(seed: number) {
  let s = seed;
  const rnd = () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const gauss = () => Math.sqrt(-2 * Math.log(Math.max(rnd(), 1e-9))) * Math.cos(6.2831853 * rnd());
  return { rnd, gauss };
}

/** Splat buffer plus each stock's centre (x, y, z, orbit radius). */
function buildSplats(stocks: DiscStock[]): { data: Float32Array<ArrayBuffer>; centres: Float32Array } {
  const N = stocks.length;
  const { rnd, gauss } = seeded(1337);
  const tierRGB = GLOW_HEX.map(hexRGB);
  // Rank to colour, continuous, with each tier's swatch at the middle of its fifth.
  const ramp = (t: number) => {
    const x = Math.min(1, Math.max(0, (t - 0.1) / 0.8)) * (tierRGB.length - 1);
    const k = Math.min(tierRGB.length - 2, Math.floor(x));
    const f = x - k;
    return [0, 1, 2].map((ch) => tierRGB[k][ch] + (tierRGB[k + 1][ch] - tierRGB[k][ch]) * f);
  };
  const RMIN = 0.23;
  const RSPAN = 0.95;
  const radiusOf = (t: number) => RMIN + RSPAN * Math.pow(t, 0.75);
  const rankAt = (R: number) => Math.pow(Math.min(1, Math.max(0, (R - RMIN) / RSPAN)), 1 / 0.75);
  // Light from the core: falls off with distance, broken into fine rings, dark lanes and swirls.
  const fallOf = (R: number) => 1 / (1 + Math.pow((R - 0.2) / 0.34, 2));
  const fadeOf = (R: number) => (R > 1.18 ? Math.exp(-(R - 1.18) * 2.4) : 1);
  const light = (R: number, th: number) => {
    const band = 0.5 + 0.5 * Math.sin(R * 64 + 2.2 * Math.sin(R * 17) + 0.6 * Math.sin(th * 3 + R * 11));
    const fine = 0.7 + 0.3 * Math.sin(R * 170 + 1.5 * Math.sin(th * 5 + R * 40));
    const swirl = 0.6 + 0.4 * Math.sin(th * 7 + R * 23 + 3 * Math.sin(th * 2));
    return fallOf(R) * (0.15 + 0.85 * band * band) * fine * swirl;
  };

  // One wedge of the disc per sector, sized by its share of the list.
  const counts = new Map<string, number>();
  for (const s of stocks) counts.set(s.sector ?? "", (counts.get(s.sector ?? "") ?? 0) + 1);
  const sectors = [...counts.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : counts.get(b)! - counts.get(a)!));
  const gap = 0.02;
  const avail = Math.PI * 2 - gap * sectors.length;
  const wedges = new Map<string, [number, number]>();
  let a0 = 0;
  for (const k of sectors) {
    const w = (counts.get(k)! / N) * avail;
    wedges.set(k, [a0, w]);
    a0 += w + gap;
  }

  const out: number[] = [];
  // sig = 1-sigma size along the orbit (world units); asp = orbit / radial ratio, 0 = a round glow.
  const push = (x: number, y: number, z: number, rgb: number[], alpha: number, sig: number, asp: number, R: number, id: number) => {
    out.push(x, y, z, rgb[0], rgb[1], rgb[2], alpha, sig, asp, rnd(), R, id);
  };
  const centres = new Float32Array(N * 4);

  for (let i = 0; i < N; i++) {
    const t = N > 1 ? i / (N - 1) : 0;
    const w = 1 - t;
    const R = radiusOf(t) + gauss() * 0.008;
    const [w0, ww] = wedges.get(stocks[i].sector ?? "")!;
    const th = w0 + (0.05 + 0.9 * rnd()) * ww;
    const ct = Math.cos(th);
    const sn = Math.sin(th);
    const cx = R * ct;
    const cz = R * sn;
    const cy = gauss() * 0.004;
    centres.set([cx, cy, cz, R], i * 4);

    const M = Math.round(24 + 60 * w * w);
    const spread = 0.01 + 0.016 * w;
    for (let j = 0; j < M; j++) {
      const along = gauss() * spread * 4.5;
      const across = gauss() * spread * 0.35;
      const tint = ramp(t + gauss() * 0.04);
      const wh = 0.15 * Math.pow(w, 3) * rnd();
      const rgb = tint.map((v) => v + (1 - v) * wh);
      const sig = (0.005 + 0.016 * rnd() * rnd()) * (0.7 + 0.8 * w);
      const alpha = (0.16 + 0.3 * rnd()) * (0.45 + 0.45 * w);
      push(cx - sn * along + ct * across, cy, cz + ct * along + sn * across, rgb, alpha, sig, 6 + 8 * rnd(), R, i);
    }
    // One wide, faint splat per stock so each cloud reads as a body, not dots.
    push(cx, cy, cz, ramp(t), 0.03 + 0.06 * w, 0.018 + 0.02 * w, 4, R, i);
  }

  // The disc itself: fine streaks along the orbits, out past the last stock into the dark.
  // The inner edge is sharp: a bright gold-white rim, with a clear gap inside it.
  for (let k = 0; k < 44000; k++) {
    const R = 0.2 + 1.5 * Math.pow(rnd(), 1.15);
    const th = rnd() * Math.PI * 2;
    // The rim faces the star, so it is lit evenly, without the lanes further out.
    const rim = Math.exp(-Math.pow((R - 0.235) / 0.035, 2));
    const edge = Math.min(1, (R - 0.2) / 0.01);
    const lit = light(R, th) * (1 - rim) + 0.85 * rim;
    const rgb = ramp(rankAt(R)).map((v) => v + (1 - v) * 0.2 * rim);
    const alpha = (0.05 + 0.13 * rnd()) * lit * fadeOf(R) * edge * (1 + 4 * rim);
    const sig = (0.004 + 0.012 * rnd() * rnd()) * (0.8 + 0.8 * R);
    push(R * Math.cos(th), gauss() * 0.003 * (1 + R), R * Math.sin(th), rgb, alpha, sig, 4 + 10 * rnd(), R, -1);
  }
  // Gas under the streaks, so the lanes between them glow faintly instead of going black.
  for (let k = 0; k < 1500; k++) {
    const R = 0.21 + 1.5 * Math.pow(rnd(), 1.1);
    const th = rnd() * Math.PI * 2;
    const alpha = (0.02 + 0.025 * rnd()) * fallOf(R) * fadeOf(R);
    const sig = (0.02 + 0.025 * rnd()) * (0.8 + 0.5 * R);
    push(R * Math.cos(th), 0, R * Math.sin(th), ramp(rankAt(R)), alpha, sig, 2.5 + 2.5 * rnd(), R, -1);
  }
  // A thin, faint ring inside the clear gap around the core.
  for (let k = 0; k < 900; k++) {
    const R = 0.11 + gauss() * 0.005;
    const th = rnd() * Math.PI * 2;
    push(R * Math.cos(th), 0, R * Math.sin(th), [1, 0.85, 0.62], 0.025 + 0.035 * rnd(), 0.006, 6, R, -1);
  }
  // The core: a white-hot point with a bloom of warm light above the disc.
  push(0, 0.01, 0, [1, 1, 1], 1, 0.009, 0, 0, -1);
  push(0, 0.01, 0, [1, 0.95, 0.85], 0.7, 0.018, 0, 0, -1);
  for (let k = 0; k < 6; k++) push(0, 0.01, 0, [1, 0.78, 0.5], 0.035 + 0.03 * rnd(), 0.025 + 0.04 * rnd(), 0, 0, -1);

  return { data: new Float32Array(out), centres };
}

const SPLAT_VS = `#version 300 es
precision highp float;
in vec2 aCorner;
in vec3 aPos;
in vec4 aCol;
in vec4 aShape;
in float aId;
uniform vec2 uRes, uCenter;
uniform float uFocal, uDist, uSpin, uSway, uTilt, uYaw, uRoll, uTime, uHi, uHiMix, uFade0, uFade1;
out vec4 vCol;
out vec2 vUV;
vec3 xf(vec3 p, float R) {
  float a = uSpin + uSway * (1.0 - R);
  float c = cos(a), s = sin(a);
  p = vec3(c * p.x - s * p.z, p.y, s * p.x + c * p.z);
  float ct = cos(uTilt), st = sin(uTilt);
  p = vec3(p.x, ct * p.y + st * p.z, -st * p.y + ct * p.z);
  float cy = cos(uYaw), sy = sin(uYaw);
  return vec3(cy * p.x + sy * p.z, p.y, -sy * p.x + cy * p.z);
}
vec2 proj(vec3 p) {
  vec2 q = p.xy * uFocal / (uDist + p.z);
  float cr = cos(uRoll), sr = sin(uRoll);
  return uCenter + vec2(cr * q.x - sr * q.y, sr * q.x + cr * q.y);
}
void main() {
  float R = aShape.w;
  vec3 p = xf(aPos, R);
  float z = uDist + p.z;
  if (z < 0.4) {
    vCol = vec4(0.0);
    vUV = vec2(9.0);
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }
  vec2 s0 = proj(p);
  float isHi = step(abs(aId - uHi), 0.5);
  float hi = isHi * uHiMix;
  float sig = aShape.x * (1.0 + 0.6 * hi);
  float a;
  float b;
  float c;
  if (aShape.y > 0.0) {
    // In-plane axes (along the orbit, along the radius) projected to the screen.
    vec3 rn = normalize(vec3(aPos.x + 1e-5, 0.0, aPos.z));
    vec3 tn = vec3(-rn.z, 0.0, rn.x);
    vec2 vt = (proj(xf(aPos + tn * 0.01, R)) - s0) * (sig / 0.01);
    vec2 vr = (proj(xf(aPos + rn * 0.01, R)) - s0) * (sig / aShape.y / 0.01);
    a = vt.x * vt.x + vr.x * vr.x;
    b = vt.x * vt.y + vr.x * vr.y;
    c = vt.y * vt.y + vr.y * vr.y;
  } else {
    float px = sig * uFocal / z;
    a = px * px;
    b = 0.0;
    c = px * px;
  }
  // Low-pass so no splat shrinks below a pixel; dim it by the area it gained.
  float det0 = max(a * c - b * b, 1e-8);
  a += 0.3;
  c += 0.3;
  float det = a * c - b * b;
  float mid = 0.5 * (a + c);
  float spread = sqrt(max(mid * mid - det, 0.0));
  float l1 = mid + spread;
  float l2 = max(mid - spread, 0.05);
  vec2 e1 = abs(b) > 1e-6 ? normalize(vec2(b, l1 - a)) : (a >= c ? vec2(1.0, 0.0) : vec2(0.0, 1.0));
  vec2 e2 = vec2(-e1.y, e1.x);
  vec2 off = aCorner.x * e1 * (3.0 * sqrt(l1)) + aCorner.y * e2 * (3.0 * sqrt(l2));
  vUV = aCorner * 3.0;
  float alpha = aCol.a * sqrt(det0 / det);
  alpha *= 0.82 + 0.18 * sin(uTime * (0.5 + aShape.z) + aShape.z * 40.0);
  alpha *= mix(1.0, 0.55, uHiMix * (1.0 - isHi));
  alpha *= mix(0.22, 1.0, smoothstep(uFade0, uFade1, s0.x));
  vCol = vec4(aCol.rgb * (1.0 + 1.2 * hi), alpha);
  gl_Position = vec4((s0 + off) / uRes * 2.0 - 1.0, 0.0, 1.0);
}`;

const SPLAT_FS = `#version 300 es
precision highp float;
in vec4 vCol;
in vec2 vUV;
out vec4 outColor;
void main() {
  float r2 = dot(vUV, vUV);
  if (r2 > 9.0) discard;
  outColor = vec4(vCol.rgb * vCol.a * exp(-0.5 * r2) * 1.2, 1.0);
}`;

const RESOLVE_VS = `#version 300 es
void main() {
  gl_Position = vec4(gl_VertexID == 1 ? 3.0 : -1.0, gl_VertexID == 2 ? 3.0 : -1.0, 0.0, 1.0);
}`;

const RESOLVE_FS = `#version 300 es
precision highp float;
uniform sampler2D uScene;
uniform vec4 uStops[12];
uniform int uCount;
uniform float uCut, uTime, uArtH;
uniform vec3 uStar;
uniform vec2 uFade;
out vec4 outColor;
const float BAYER[16] = float[16](0.0, 8.0, 2.0, 10.0, 12.0, 4.0, 14.0, 6.0, 3.0, 11.0, 1.0, 9.0, 15.0, 7.0, 13.0, 5.0);
float hash(vec2 p) {
  p = fract(p * vec2(443.897, 441.423));
  p += dot(p, p.yx + 19.19);
  return fract((p.x + p.y) * p.x);
}
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  ivec2 q = p * 2;
  vec3 c = texelFetch(uScene, q, 0).rgb + texelFetch(uScene, q + ivec2(1, 0), 0).rgb
    + texelFetch(uScene, q + ivec2(0, 1), 0).rgb + texelFetch(uScene, q + ivec2(1, 1), 0).rgb;
  // Exposure: lifts the inner rim into the golds and whites of the palette.
  float l = dot(c * 0.25, vec3(0.30, 0.55, 0.15)) * 1.55;
  // The star's four-point glint, one art pixel wide.
  vec2 d = abs(vec2(p) - uStar.xy);
  float g = 0.0;
  if (d.y < 0.5) g = exp(-d.x / uStar.z);
  if (d.x < 0.5) g = max(g, exp(-d.y / (uStar.z * 0.55)));
  l = 1.0 - (1.0 - l) * (1.0 - 0.95 * g);
  // Background stars: single art pixels fixed to the grid, twinkling slowly.
  float h = hash(vec2(p));
  if (h > 0.9968 && l < 0.12) {
    float k = fract(h * 7919.0);
    float tw = 0.6 + 0.4 * sin(uTime * (0.4 + 2.0 * k) + k * 60.0);
    l = max(l, (0.07 + 0.22 * k * k) * tw * mix(0.45, 1.0, smoothstep(uFade.x, uFade.y, float(p.x))));
  }
  if (l <= uCut) {
    outColor = vec4(uStops[0].rgb, 1.0);
    return;
  }
  int lo = 0;
  for (int i = 1; i < 11; i++) {
    if (i >= uCount - 1 || l <= uStops[i].a) break;
    lo = i;
  }
  vec4 a = uStops[lo];
  vec4 b = uStops[lo + 1];
  float share = clamp((l - a.a) / (b.a - a.a), 0.0, 1.0);
  // Bayer rank anchored top-left, so the pattern doesn't crawl when the canvas grows.
  int y = int(uArtH) - 1 - p.y;
  float rank = (BAYER[(p.x & 3) + ((y & 3) << 2)] + 0.5) / 16.0;
  outColor = vec4(share >= rank ? b.rgb : a.rgb, 1.0);
}`;

function compile(gl: WebGL2RenderingContext, vsrc: string, fsrc: string): WebGLProgram | null {
  const shader = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.warn(gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  };
  const v = shader(gl.VERTEX_SHADER, vsrc);
  const f = shader(gl.FRAGMENT_SHADER, fsrc);
  if (!v || !f) return null;
  const p = gl.createProgram()!;
  gl.attachShader(p, v);
  gl.attachShader(p, f);
  gl.linkProgram(p);
  gl.deleteShader(v);
  gl.deleteShader(f);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
    console.warn(gl.getProgramInfoLog(p));
    gl.deleteProgram(p);
    return null;
  }
  return p;
}

type View = { cx: number; cy: number; f: number; fade0: number; fade1: number };
type Art = { w: number; h: number; px: number; sx: number; sy: number };

const SPLAT_UNIFORMS = ["uRes", "uCenter", "uFocal", "uDist", "uSpin", "uSway", "uTilt", "uYaw", "uRoll", "uTime", "uHi", "uHiMix", "uFade0", "uFade1"] as const;
const RESOLVE_UNIFORMS = ["uScene", "uStops", "uCount", "uCut", "uTime", "uArtH", "uStar", "uFade"] as const;

export class SplatDisc {
  /** False when the browser can't draw WebGL2; the caller shows a fallback. */
  readonly ok: boolean;

  private readonly canvas: HTMLCanvasElement;
  private readonly host: HTMLElement;
  private readonly n: number;
  /** Index of the #1 stock, which the centre star names. */
  private readonly top: number;
  /** The centre star in art pixels, from the last drawn frame. */
  private star = [0, 0];
  /** Whether the label is anchored on the star rather than a stock's own cloud. */
  private atStar = false;
  private readonly cb: DiscCallbacks;
  private gl: WebGL2RenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private rprog: WebGLProgram | null = null;
  private vao: WebGLVertexArrayObject | null = null;
  private rvao: WebGLVertexArrayObject | null = null;
  private buffers: WebGLBuffer[] = [];
  private tex: WebGLTexture | null = null;
  private fbo: WebGLFramebuffer | null = null;
  private u = {} as Record<(typeof SPLAT_UNIFORMS)[number], WebGLUniformLocation | null>;
  private ru = {} as Record<(typeof RESOLVE_UNIFORMS)[number], WebGLUniformLocation | null>;
  private count = 0;
  private centres: Float32Array = new Float32Array(0);
  private screen: Float32Array = new Float32Array(0);
  private sceneSize: [number, number] | null = null;
  private art: Art = { w: 1, h: 1, px: PIXEL, sx: PIXEL, sy: PIXEL };
  private view: View | null = null;
  private wide: MediaQueryList;
  private reduce: boolean;
  private ro: ResizeObserver | null = null;
  private io: IntersectionObserver | null = null;
  private visible = true;
  private raf = 0;
  private prev = 0;
  private lastDraw = -1e9;
  private clock = 0;
  private yaw = 0;
  private tiltOff = 0;
  private hiMix = 0;
  private lastHi = -10;
  private shown = -1;
  private hoverId = -1;
  private pinned = -1;
  private drawn = false;
  private tagEl: HTMLElement | null = null;
  private ptr = { tx: 0, ty: 0, x: 0, y: 0, inside: false };

  constructor(canvas: HTMLCanvasElement, host: HTMLElement, stocks: DiscStock[], cb: DiscCallbacks) {
    this.canvas = canvas;
    this.host = host;
    this.n = stocks.length;
    this.top = stocks.reduce((best, s, i) => (s.rank < stocks[best].rank ? i : best), 0);
    this.cb = cb;
    this.wide = window.matchMedia(WIDE);
    this.reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.ok = this.init(stocks);
  }

  private init(stocks: DiscStock[]): boolean {
    const gl = this.canvas.getContext("webgl2", { alpha: false, antialias: false, premultipliedAlpha: false });
    if (!gl) return false;
    const prog = compile(gl, SPLAT_VS, SPLAT_FS);
    const rprog = compile(gl, RESOLVE_VS, RESOLVE_FS);
    if (!prog || !rprog) return false;
    this.gl = gl;
    this.prog = prog;
    this.rprog = rprog;

    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    const quad = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const corner = gl.getAttribLocation(prog, "aCorner");
    gl.enableVertexAttribArray(corner);
    gl.vertexAttribPointer(corner, 2, gl.FLOAT, false, 0, 0);
    gl.vertexAttribDivisor(corner, 0);

    const { data, centres } = buildSplats(stocks);
    this.centres = centres;
    this.screen = new Float32Array(this.n * 2);
    this.count = data.length / STRIDE;
    const buf = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    this.buffers = [quad, buf];
    const attr = (name: string, size: number, offset: number) => {
      const loc = gl.getAttribLocation(prog, name);
      if (loc < 0) return;
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, STRIDE * 4, offset);
      gl.vertexAttribDivisor(loc, 1);
    };
    attr("aPos", 3, 0);
    attr("aCol", 4, 12);
    attr("aShape", 4, 28);
    attr("aId", 1, 44);
    gl.bindVertexArray(null);
    this.rvao = gl.createVertexArray();

    for (const n of SPLAT_UNIFORMS) this.u[n] = gl.getUniformLocation(prog, n);
    for (const n of RESOLVE_UNIFORMS) this.ru[n] = gl.getUniformLocation(rprog, n);

    // Each stop sits at its own luminance, so the resolve keeps the splats'
    // brightness and only snaps it to these colours.
    const stops = new Float32Array(PALETTE.length * 4);
    PALETTE.forEach((h, i) => stops.set([...hexRGB(h), STOP_LUMA[i]], i * 4));
    gl.useProgram(rprog);
    gl.uniform4fv(this.ru.uStops, stops);
    gl.uniform1i(this.ru.uCount, PALETTE.length);
    gl.uniform1f(this.ru.uCut, LUMA_CUT);
    gl.uniform1i(this.ru.uScene, 0);

    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindTexture(gl.TEXTURE_2D, null);
    this.fbo = gl.createFramebuffer();
    gl.disable(gl.DEPTH_TEST);

    this.resize();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.canvas);
    this.io = new IntersectionObserver((es) => {
      this.visible = es[0].isIntersecting;
    });
    this.io.observe(this.canvas);
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      if (this.visible) this.frame(now);
    };
    this.raf = requestAnimationFrame(loop);
    return true;
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.io?.disconnect();
    this.host.style.cursor = "";
    const gl = this.gl;
    if (!gl) return;
    for (const b of this.buffers) gl.deleteBuffer(b);
    gl.deleteVertexArray(this.vao);
    gl.deleteVertexArray(this.rvao);
    gl.deleteProgram(this.prog);
    gl.deleteProgram(this.rprog);
    gl.deleteTexture(this.tex);
    gl.deleteFramebuffer(this.fbo);
    this.gl = null;
  }

  /** The label element; the disc moves it onto the shown stock every frame. */
  setTag(el: HTMLElement | null) {
    this.tagEl = el;
  }

  /** A stock to light up and label while nothing is pointed at (-1 = none). */
  setPinned(index: number) {
    this.pinned = index;
    this.hover();
  }

  /** Pointer position in client coordinates; the host's box drives the parallax. */
  move(clientX: number, clientY: number) {
    const hr = this.host.getBoundingClientRect();
    this.ptr.tx = ((clientX - hr.left) / hr.width) * 2 - 1;
    this.ptr.ty = ((clientY - hr.top) / hr.height) * 2 - 1;
    const r = this.canvas.getBoundingClientRect();
    this.ptr.x = clientX - r.left;
    this.ptr.y = clientY - r.top;
    this.ptr.inside = this.ptr.x >= 0 && this.ptr.y >= 0 && this.ptr.x <= r.width && this.ptr.y <= r.height;
    this.hover();
  }

  leave() {
    this.ptr.tx = 0;
    this.ptr.ty = 0;
    this.ptr.inside = false;
    this.hover();
  }

  /** The stock under a client point, from the last drawn frame (-1 = none). */
  stockAt(clientX: number, clientY: number): number {
    const r = this.canvas.getBoundingClientRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    if (x < 0 || y < 0 || x > r.width || y > r.height) return -1;
    return this.nearStar(x, y) ? this.top : this.pick(x, y);
  }

  private resize() {
    const c = this.canvas;
    const gl = this.gl;
    if (!gl) return;
    const cw = Math.max(1, c.clientWidth);
    const ch = Math.max(1, c.clientHeight);
    const wide = this.wide.matches;
    const px = wide ? PIXEL : Math.max(2, PIXEL - 1);
    const w = Math.max(1, Math.round(cw / px));
    const h = Math.max(1, Math.round(ch / px));
    if (c.width !== w) c.width = w;
    if (c.height !== h) c.height = h;
    this.art = { w, h, px, sx: cw / w, sy: ch / h };
    if (!this.sceneSize || this.sceneSize[0] !== w * 2 || this.sceneSize[1] !== h * 2) {
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w * 2, h * 2, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.bindTexture(gl.TEXTURE_2D, null);
      gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      this.sceneSize = [w * 2, h * 2];
    }
    // In art pixels. Wide: right of the copy, fading under it. Narrow: centred, below the copy.
    this.view = wide
      ? { cx: 0.66 * w, cy: 0.58 * h, f: Math.min(0.9 * w, 1.6 * h), fade0: 0.3 * w, fade1: 0.52 * w }
      : { cx: 0.5 * w, cy: 0.62 * h, f: Math.min(1.3 * w, 1.5 * h), fade0: -2, fade1: -1 };
    this.lastDraw = -1e9;
  }

  /** Nearest stock centre within PICK_RADIUS of a canvas point; `keep` is the
   *  stock already named, which holds on unless another is clearly nearer. */
  private pick(cssX: number, cssY: number, keep = -1): number {
    const A = this.art;
    const V = this.view;
    if (!V || !this.drawn) return -1;
    const px = cssX / A.sx;
    const py = A.h - cssY / A.sy;
    const reach = Math.pow(PICK_RADIUS / A.sx, 2);
    const dist = (i: number) => {
      // Stocks passing under the copy are faded out, so they can't be pointed at.
      if (this.screen[i * 2] < V.fade1) return Infinity;
      const dx = this.screen[i * 2] - px;
      const dy = this.screen[i * 2 + 1] - py;
      return dx * dx + dy * dy;
    };
    let best = -1;
    let bd = reach;
    for (let i = 0; i < this.n; i++) {
      const d = dist(i);
      if (d < bd) {
        bd = d;
        best = i;
      }
    }
    if (keep >= 0 && best !== keep) {
      const dk = dist(keep);
      if (dk < reach && dk < bd * PICK_STICKY * PICK_STICKY) return keep;
    }
    return best;
  }

  /** Whether a canvas point is on the centre star. */
  private nearStar(cssX: number, cssY: number): boolean {
    if (!this.drawn || this.n === 0) return false;
    const A = this.art;
    const dx = (this.star[0] + 0.5) * A.sx - cssX;
    const dy = (A.h - this.star[1] - 0.5) * A.sy - cssY;
    return dx * dx + dy * dy < STAR_RADIUS * STAR_RADIUS;
  }

  /**
   * Name the stock under the pointer (or the pinned one) and move the label onto
   * it. Runs on every pointer move against the last drawn frame, as well as on
   * each redraw, so the label answers the pointer at once instead of on the
   * next 12 fps beat.
   */
  private hover() {
    if (!this.drawn) return;
    const A = this.art;
    const P = this.screen;
    const c = this.canvas;
    this.atStar = this.ptr.inside && this.nearStar(this.ptr.x, this.ptr.y);
    this.hoverId = !this.ptr.inside
      ? -1
      : this.atStar
        ? this.top
        : this.pick(this.ptr.x, this.ptr.y, this.hoverId);
    this.host.style.cursor = this.hoverId >= 0 ? "pointer" : "";
    const id = this.hoverId >= 0 ? this.hoverId : this.pinned;
    if (id !== this.shown) {
      this.shown = id;
      this.cb.onShow(id);
    }
    if (id < 0) return;
    this.lastHi = id;
    if (this.tagEl) {
      // Snap the label to the art-pixel grid, like everything else in the view.
      const [ax, ay] = this.atStar ? this.star : [P[id * 2], P[id * 2 + 1]];
      const lx = (Math.floor(ax) + 0.5) * A.sx + c.offsetLeft;
      const ly = (A.h - Math.floor(ay) - 0.5) * A.sy + c.offsetTop;
      this.tagEl.style.transform = `translate(${lx.toFixed(1)}px, ${ly.toFixed(1)}px)`;
      // Near the right edge, the label sits on the left of its stock.
      this.tagEl.dataset.flip = lx > c.clientWidth - 240 ? "1" : "0";
    }
  }

  private frame(now: number) {
    const gl = this.gl;
    const V = this.view;
    if (!gl || !V || !this.sceneSize) return;
    const animate = !this.reduce;
    if (animate && this.prev) this.clock += Math.min(now - this.prev, 50) / 1000;
    this.prev = now;
    // Pixel art moves on a beat: redraw 12 times a second, not on every display frame.
    if (now - this.lastDraw < 1000 / 12) return;
    this.lastDraw = now;
    const t = this.clock;
    const spin = 0.6 + t * 0.03;
    const sway = 0.2 * Math.sin(t * 0.08);
    const tx = animate ? this.ptr.tx : 0;
    const ty = animate ? this.ptr.ty : 0;
    this.yaw += (tx * 0.12 - this.yaw) * 0.18;
    this.tiltOff += (ty * 0.08 - this.tiltOff) * 0.18;
    const tilt = CAM.tilt + this.tiltOff;
    const A = this.art;

    // Stock centres in art pixels, same transform as the vertex shader, for pointing and the label.
    const ct = Math.cos(tilt);
    const st = Math.sin(tilt);
    const cyw = Math.cos(this.yaw);
    const syw = Math.sin(this.yaw);
    const cr = Math.cos(CAM.roll);
    const sr = Math.sin(CAM.roll);
    const project = (x: number, y: number, z: number, R: number, out: Float32Array | number[], k: number) => {
      const a = spin + sway * (1 - R);
      const ca = Math.cos(a);
      const sa = Math.sin(a);
      const x1 = ca * x - sa * z;
      const z1 = sa * x + ca * z;
      const y2 = ct * y + st * z1;
      const z2 = -st * y + ct * z1;
      const x3 = cyw * x1 + syw * z2;
      const z3 = -syw * x1 + cyw * z2;
      const f = V.f / (CAM.dist + z3);
      out[k] = V.cx + cr * x3 * f - sr * y2 * f;
      out[k + 1] = V.cy + sr * x3 * f + cr * y2 * f;
    };
    const C = this.centres;
    const P = this.screen;
    for (let i = 0; i < this.n; i++) project(C[i * 4], C[i * 4 + 1], C[i * 4 + 2], C[i * 4 + 3], P, i * 2);
    const star = this.star;
    project(0, 0.01, 0, 0, star, 0);

    this.drawn = true;
    this.hover();
    // The named stock's splats brighten over a couple of beats.
    this.hiMix += ((this.shown >= 0 ? 1 : 0) - this.hiMix) * 0.6;

    // Pass 1: splats into the 2x picture.
    const ss = 2;
    const u = this.u;
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.viewport(0, 0, this.sceneSize[0], this.sceneSize[1]);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    // Screen blending: order-free, and dense regions brighten toward white without clipping.
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_COLOR);
    gl.useProgram(this.prog);
    gl.bindVertexArray(this.vao);
    gl.uniform2f(u.uRes, this.sceneSize[0], this.sceneSize[1]);
    gl.uniform2f(u.uCenter, V.cx * ss, V.cy * ss);
    gl.uniform1f(u.uFocal, V.f * ss);
    gl.uniform1f(u.uDist, CAM.dist);
    gl.uniform1f(u.uSpin, spin);
    gl.uniform1f(u.uSway, sway);
    gl.uniform1f(u.uTilt, tilt);
    gl.uniform1f(u.uYaw, this.yaw);
    gl.uniform1f(u.uRoll, CAM.roll);
    gl.uniform1f(u.uTime, t);
    gl.uniform1f(u.uHi, this.hiMix > 0.01 ? this.lastHi : -10);
    gl.uniform1f(u.uHiMix, this.hiMix);
    gl.uniform1f(u.uFade0, V.fade0 * ss);
    gl.uniform1f(u.uFade1, V.fade1 * ss);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, this.count);

    // Pass 2: resolve to art pixels on the palette.
    const r = this.ru;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, A.w, A.h);
    gl.disable(gl.BLEND);
    gl.useProgram(this.rprog);
    gl.bindVertexArray(this.rvao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.uniform1f(r.uTime, t);
    gl.uniform1f(r.uArtH, A.h);
    gl.uniform3f(r.uStar, Math.floor(star[0]), Math.floor(star[1]), Math.max(3, A.w / 80));
    gl.uniform2f(r.uFade, V.fade0, V.fade1);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindVertexArray(null);
  }
}
