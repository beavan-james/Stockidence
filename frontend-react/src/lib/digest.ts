import type { DigestInput, DigestPeriod, DigestStory } from "@/types/api";

/** A digest warns when a session went this long without an article. */
export const GAP_WARN_MINUTES = 120;

export const INPUTS: { key: DigestInput; label: string }[] = [
  { key: "event", label: "Event" },
  { key: "reaction", label: "Price move" },
  { key: "size", label: "Company size" },
  { key: "on_site", label: "On the site" },
];

export const CATEGORY_LABELS: Record<string, string> = {
  deal: "Deal",
  earnings: "Earnings",
  macro: "Macro",
  policy: "Policy",
};

/** "on the day" / "on the week": what a story's move covers. */
export const MOVE_SPAN: Record<DigestPeriod, string> = { daily: "on the day", weekly: "on the week" };
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
/** The plain-words reading of one score input for one story. */
export function inputReading(
  key: DigestInput,
  s: DigestStory,
  period: DigestPeriod,
  ranked: (t: string) => boolean,
): string {
  switch (key) {
    case "event":
      return s.categories.length ? s.categories.map((c) => CATEGORY_LABELS[c] ?? c).join(", ") : (s.source ?? "");
    case "reaction":
      return s.move_ticker && s.move_return != null
        ? `${s.move_ticker} ${signedPct(s.move_return)} ${MOVE_SPAN[period]}`
        : "No price for the stock it leads with";
    case "size":
      return s.tickers.length ? s.tickers[0] : "Names no stock";
    case "on_site": {
      const named = s.tickers.filter(ranked);
      return (s.components.on_site ?? 0) > 0
        ? `${named.length ? named.join(", ") : "A named stock"} is in a site ranking`
        : "Names no stock the site ranks";
    }
  }
}
