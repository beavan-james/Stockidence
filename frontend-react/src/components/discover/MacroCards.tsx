import { snapshotLabel } from "@/lib/tiers";
import type { Commodity, MacroMetric, SeriesPoint } from "@/types/api";

function Sparkline({ points }: { points: SeriesPoint[] }) {
  const values = points.map((p) => p.value).filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const coords = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${28 - ((v - min) / span) * 24}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-10 w-full">
      <polyline
        points={coords}
        fill="none"
        className="stroke-accent transition-colors group-hover:stroke-accent-strong"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Macro readings with a sparkline of the recent series, then commodity prices, on one grid. */
export function MacroGrid({ metrics, commodities }: { metrics: MacroMetric[]; commodities: Commodity[] }) {
  return (
    <div className="grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map((m) => (
        <div key={m.label} className="group border-t border-line pt-4">
          <p className="text-sm text-ink-secondary">{m.label}</p>
          <p className="num mt-1 text-3xl">
            {m.value?.toLocaleString("en-US")}
            <span className="ml-1 text-xs text-ink-muted">{m.unit}</span>
          </p>
          <div className="mt-3">
            <Sparkline points={m.series} />
          </div>
          <p className="mt-2 text-xs text-ink-muted">
            {m.detail} · as of {snapshotLabel(m.as_of)}
          </p>
        </div>
      ))}
      {commodities.map((c) => (
        <div key={c.nominal} className="border-t border-line pt-4">
          <p className="text-sm text-ink-secondary">{c.label}</p>
          <p className="num mt-1 text-3xl">${c.price?.toLocaleString("en-US", { minimumFractionDigits: 2 })}</p>
          <p className="mt-2 text-xs text-ink-muted">{c.unit}</p>
        </div>
      ))}
    </div>
  );
}
