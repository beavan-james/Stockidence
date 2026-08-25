import { Card, CardContent } from "@/components/ui/card";
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
        stroke="#818cf8"
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Macro indicator cards: latest reading + sparkline of the recent series. */
export function MacroGrid({ metrics }: { metrics: MacroMetric[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {metrics.map((m) => (
        <Card key={m.label}>
          <CardContent className="space-y-2 p-5">
            <div className="flex items-baseline justify-between">
              <p className="text-sm font-medium">{m.label}</p>
              <p className="num text-lg font-semibold">
                {m.value?.toLocaleString("en-US")}
                <span className="ml-1 text-xs font-normal text-ink-muted">{m.unit}</span>
              </p>
            </div>
            <Sparkline points={m.series} />
            <p className="text-[11px] text-ink-muted">
              {m.detail} · as of {m.as_of}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function CommoditiesRow({ commodities }: { commodities: Commodity[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {commodities.map((c) => (
        <Card key={c.nominal}>
          <CardContent className="flex items-baseline justify-between p-5">
            <p className="text-sm font-medium">{c.label}</p>
            <div className="text-right">
              <p className="num text-lg font-semibold">
                ${c.price?.toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </p>
              <p className="text-[11px] text-ink-muted">{c.unit}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
