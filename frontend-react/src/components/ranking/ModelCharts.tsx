import { featureMeta } from "@/lib/features";
import { quarterLabel } from "@/lib/tiers";
import type { ModelOverview, RankedTicker } from "@/types/api";

/** Per-quarter lead of the model's top 20 over the S&P 500 (bars above/below zero). */
export function ExcessBars({ quarters, height = 72 }: { quarters: ModelOverview["track_record"]; height?: number }) {
  const rows = quarters
    .filter((q) => q.top20_return != null && q.spx_return != null)
    .map((q) => ({ quarter: q.quarter, excess: q.top20_return! - q.spx_return! }));
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.excess)), 0.01);
  const down = Math.round(height * 0.35);
  return (
    <div className="flex gap-[3px]">
      {rows.map((r) => {
        const h = (Math.abs(r.excess) / max) * height;
        const label = `${quarterLabel(r.quarter)}: ${r.excess >= 0 ? "+" : ""}${(r.excess * 100).toFixed(1)} pp`;
        return (
          <div key={r.quarter} className="flex flex-1 flex-col" title={label}>
            <div className="flex items-end border-b border-white/20" style={{ height }}>
              {r.excess > 0 && (
                <div
                  className="w-full"
                  style={{ height: h, background: "linear-gradient(180deg, var(--color-accent), var(--color-cobalt))" }}
                />
              )}
            </div>
            <div style={{ height: down }}>
              {r.excess < 0 && (
                <div className="w-full bg-[#3a4256]" style={{ height: Math.min(h, down) }} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Share of the average stock's score explained by each model input. */
export function WeightBars({ weights }: { weights: ModelOverview["weights"] }) {
  const top = weights[0]?.share ?? 1;
  return (
    <div className="space-y-2.5">
      {weights.map((w) => (
        <div key={w.feature} className="grid grid-cols-[minmax(0,11rem)_1fr_2.5rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-secondary">{featureMeta(w.feature).label}</span>
          <div className="h-[7px] overflow-hidden bg-white/[0.06]">
            <div
              className="h-full"
              style={{
                width: `${(w.share / top) * 100}%`,
                background: "linear-gradient(90deg, var(--color-cobalt), var(--color-accent))",
              }}
            />
          </div>
          <span className="num text-right text-ink-secondary">{Math.round(w.share * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

/** Sector counts within the top fifth of the list. */
export function SectorTilt({ items }: { items: RankedTicker[] }) {
  const fifth = items.slice(0, Math.max(1, Math.round(items.length / 5)));
  const counts = new Map<string, number>();
  for (const r of fifth) counts.set(r.sector ?? "Other", (counts.get(r.sector ?? "Other") ?? 0) + 1);
  const rows = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);
  const max = rows[0]?.[1] ?? 1;
  return (
    <div className="space-y-2.5">
      {rows.map(([sector, count]) => (
        <div key={sector} className="grid grid-cols-[minmax(0,11rem)_1fr_1.75rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-secondary">{sector}</span>
          <div className="h-2 overflow-hidden bg-white/[0.06]">
            <div
              className="h-full"
              style={{
                width: `${(count / max) * 100}%`,
                background: "linear-gradient(90deg, var(--color-cobalt), var(--color-accent))",
              }}
            />
          </div>
          <span className="num text-right text-ink-secondary">{count}</span>
        </div>
      ))}
    </div>
  );
}
