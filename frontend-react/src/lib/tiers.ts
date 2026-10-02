import type { RankedTicker } from "@/types/api";

/** Quintile tiers of the ranking: 0 = top fifth ... 4 = bottom fifth. */

export const TIER_COLORS = [
  "var(--color-tier-1)",
  "var(--color-tier-2)",
  "var(--color-tier-3)",
  "var(--color-tier-4)",
  "var(--color-tier-5)",
] as const;

export const TIER_NAMES = [
  "Top fifth",
  "Second fifth",
  "Middle fifth",
  "Fourth fifth",
  "Bottom fifth",
] as const;

/** Same rule as the API's _tier: equal-size quintiles by rank. */
export function tierOf(rank: number, universeSize: number): number {
  return Math.min(4, Math.floor(((rank - 1) * 5) / Math.max(universeSize, 1)));
}

/** "Top 3%" style label: the share of the list at or above this rank. */
export function topPercent(rank: number, universeSize: number): number {
  return Math.max(1, Math.round((rank / Math.max(universeSize, 1)) * 100));
}

/** "Q2 2026" from a quarter-start ISO date ("2026-04-01"). */
export function quarterLabel(isoDate: string): string {
  const [year, month] = isoDate.split("-").map(Number);
  return `Q${Math.floor((month - 1) / 3) + 1} ${year}`;
}

/** Headline sector: the one holding the largest share of the top fifth. */
export function leadingSector(items: RankedTicker[]): { sector: string; share: number } | null {
  const fifth = items.slice(0, Math.max(1, Math.round(items.length / 5)));
  const counts = new Map<string, number>();
  for (const r of fifth) if (r.sector) counts.set(r.sector, (counts.get(r.sector) ?? 0) + 1);
  const best = [...counts.entries()].sort((a, b) => b[1] - a[1])[0];
  return best ? { sector: best[0], share: best[1] / fifth.length } : null;
}
