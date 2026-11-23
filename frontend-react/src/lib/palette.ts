/**
 * The site's pixel-art palette and dither, shared by the home page's disc (on
 * the GPU) and the starfield behind the other pages (on the CPU).
 */

/** Dark to light: black, deep-space plums, rust and copper, the galaxy
 *  oranges, then gold to white-hot. Every art pixel is one of these. */
export const PALETTE = [
  "#000000",
  "#1d0712",
  "#360021",
  "#5a1418",
  "#86301a",
  "#b84a17",
  "#e36700",
  "#ff8d00",
  "#ffa500",
  "#ffc46b",
  "#ffe6b0",
  "#fffaf0",
];

export function hexRGB(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

/** Each stop's luminance: the scale light is measured on before it snaps to a stop. */
export const STOP_LUMA = PALETTE.map((h) => {
  const [r, g, b] = hexRGB(h);
  return 0.3 * r + 0.55 * g + 0.15 * b;
});

/** Light at or below this resolves to black. */
export const LUMA_CUT = 0.025;

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

/**
 * The palette stop an art pixel of luminance `l` resolves to: one of the two
 * stops either side of it, chosen by a 4 x 4 Bayer threshold anchored at the
 * top-left. 0 is black.
 */
export function ditherStop(l: number, x: number, y: number): number {
  if (l <= LUMA_CUT) return 0;
  let lo = 0;
  for (let i = 1; i < PALETTE.length - 1 && l > STOP_LUMA[i]; i++) lo = i;
  const a = STOP_LUMA[lo];
  const b = STOP_LUMA[lo + 1];
  const share = Math.min(1, Math.max(0, (l - a) / (b - a)));
  const rank = (BAYER[(x & 3) + ((y & 3) << 2)] + 0.5) / 16;
  return share >= rank ? lo + 1 : lo;
}
