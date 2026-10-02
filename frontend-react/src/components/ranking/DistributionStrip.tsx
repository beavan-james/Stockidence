import { Link } from "react-router-dom";

import { TIER_COLORS, tierOf } from "@/lib/tiers";
import type { RankedTicker } from "@/types/api";

/**
 * Every ranked stock as one tick, coloured by tier, best on the left.
 * The highlighted ticker is drawn taller and white so it can be found at a
 * glance; each tick links to that stock's page.
 */
export function DistributionStrip({
  items,
  highlight,
  caption,
}: {
  items: RankedTicker[];
  highlight?: string;
  caption?: string;
}) {
  const n = items.length;
  return (
    <div>
      <div className="flex h-12 items-center gap-px" role="img" aria-label={`All ${n} ranked stocks`}>
        {items.map((r) => {
          const on = r.ticker === highlight;
          return (
            <Link
              key={r.ticker}
              to={`/stocks/${r.ticker}`}
              title={`#${r.rank} ${r.ticker}`}
              className="flex-1 rounded-[1px] transition-opacity hover:opacity-70"
              style={{
                height: on ? 44 : 24,
                minWidth: on ? 3 : undefined,
                background: on ? "#fff" : TIER_COLORS[tierOf(r.rank, n)],
                boxShadow: on ? "0 0 0 3px rgba(255,255,255,.12)" : undefined,
              }}
            />
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-xs text-ink-muted">
        <span>#1 · most favoured</span>
        {caption && <span>{caption}</span>}
        <span>#{n} · least favoured</span>
      </div>
    </div>
  );
}
