import type { DigestInput } from "@/types/api";

/** A digest warns when a session went this long without an article. */
export const GAP_WARN_MINUTES = 120;

export const INPUTS: { key: DigestInput; label: string }[] = [
  { key: "coverage", label: "Coverage" },
  { key: "reaction", label: "Stock move" },
  { key: "category", label: "Story type" },
  { key: "on_site", label: "On the site" },
];

function utcDate(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function formatDay(iso: string, options: Intl.DateTimeFormatOptions): string {
  return utcDate(iso).toLocaleDateString("en-US", { ...options, timeZone: "UTC" });
}

/** "Tuesday, Sep 8" for a digest date. */
export const longDay = (iso: string) => formatDay(iso, { weekday: "long", month: "short", day: "numeric" });

/** "Tue, Sep 8" for a digest date. */
export const shortDay = (iso: string) => formatDay(iso, { weekday: "short", month: "short", day: "numeric" });

/** "Sep 8" for a digest date. */
export const monthDay = (iso: string) => formatDay(iso, { month: "short", day: "numeric" });

/** The Monday of the week a weekly digest (dated by its Friday) covers. */
export function weekStart(friday: string): string {
  const d = utcDate(friday);
  d.setUTCDate(d.getUTCDate() - 4);
  return d.toISOString().slice(0, 10);
}

export const signedPct = (v: number, digits = 1) =>
  `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(digits)}%`;

export const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

export function hoursMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h${m ? ` ${m}m` : ""}` : `${m}m`;
}
