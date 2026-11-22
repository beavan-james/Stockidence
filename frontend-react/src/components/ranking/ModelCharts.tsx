import { featureMeta } from "@/lib/features";
import { quarterLabel, snapshotLabel } from "@/lib/tiers";
import type { ModelOverview, WeeklyTrackWeek } from "@/types/api";

/** Per-quarter lead of the model's top 20 over the S&P 500 (bars above/below zero). */
export function ExcessBars({ quarters, height = 72 }: { quarters: ModelOverview["track_record"]; height?: number }) {
  const rows = quarters
    .filter((q) => q.top20_return != null && q.spx_return != null)
    .map((q) => ({ key: q.quarter, label: quarterLabel(q.quarter), excess: q.top20_return! - q.spx_return! }));
  return <LeadBars rows={rows} height={height} />;
}

/** Per-week lead of the weekly top 10 over the S&P 500; a week's bar is the
 *  week after its Friday snapshot. */
export function WeeklyExcessBars({ weeks, height = 72 }: { weeks: WeeklyTrackWeek[]; height?: number }) {
  const rows = weeks
    .filter((w) => w.top10_return != null && w.spx_return != null)
    .map((w) => ({ key: w.week, label: `Week after ${snapshotLabel(w.week)}`, excess: w.top10_return! - w.spx_return! }));
  return <LeadBars rows={rows} height={height} gap={1} />;
}

function LeadBars({
  rows,
  height,
  gap = 3,
}: {
  rows: { key: string; label: string; excess: number }[];
  height: number;
  gap?: number;
}) {
  if (rows.length === 0) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r.excess)), 0.01);
  const down = Math.round(height * 0.35);
  return (
    <div>
      <div className="flex" style={{ gap }}>
        {rows.map((r) => {
          const h = (Math.abs(r.excess) / max) * height;
          const label = `${r.label}: ${r.excess >= 0 ? "+" : ""}${(r.excess * 100).toFixed(1)} pp`;
          return (
            <div key={r.key} className="bar-target flex flex-1 flex-col" title={label}>
              <div className="flex items-end border-b border-white/20" style={{ height }}>
                {r.excess > 0 && <div className="bar w-full" style={{ height: h }} />}
              </div>
              <div style={{ height: down }}>
                {r.excess < 0 && <div className="bar bar-down w-full" style={{ height: Math.min(h, down) }} />}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-0.5 flex justify-between text-[11px] text-ink-muted">
        <span>{axis(rows[0].label)}</span>
        <span>{axis(rows[rows.length - 1].label)}</span>
      </div>
    </div>
  );
}

/** Axis ends name the first and last bar without the "Week after" lead-in. */
const axis = (label: string) => label.replace(/^Week after /, "");

/** Share of the average stock's score explained by each model input. */
export function WeightBars({ weights }: { weights: ModelOverview["weights"] }) {
  const top = weights[0]?.share ?? 1;
  return (
    <div className="space-y-2.5">
      {weights.map((w) => (
        <div key={w.feature} className="bar-target grid grid-cols-[minmax(0,11rem)_1fr_2.5rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-secondary">{featureMeta(w.feature).label}</span>
          <div className="h-[7px] bg-white/[0.06]">
            <div className="bar h-full" style={{ width: `${(w.share / top) * 100}%` }} />
          </div>
          <span className="num text-right text-ink-secondary">{Math.round(w.share * 100)}%</span>
        </div>
      ))}
    </div>
  );
}
