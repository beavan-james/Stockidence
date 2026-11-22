import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { TierLabel } from "@/components/ranking/TierLabel";
import { Input } from "@/components/ui/input";
import { Pager } from "@/components/ui/pager";
import { tierOf, topPercent } from "@/lib/tiers";
import { cn } from "@/lib/utils";
import type { RankedTicker } from "@/types/api";

const PAGE_SIZE = 10;

type Row = RankedTicker & { previous_rank?: number | null };

/** Move since the previous list: ▲ up, ▼ down; "new" if it wasn't ranked. */
function RankChange({ rank, previous }: { rank: number; previous: number | null | undefined }) {
  if (previous == null) return <span className="text-[11px] text-ink-muted">new</span>;
  const delta = previous - rank;
  if (delta === 0) return <span className="text-[11px] text-ink-muted">–</span>;
  return (
    <span className={`num whitespace-nowrap text-[11px] ${delta > 0 ? "text-accent/70" : "text-ink-muted"}`}>
      {delta > 0 ? "▲" : "▼"}
      {Math.abs(delta)}
    </span>
  );
}

/** The full ranked list: filter by ticker or sector, 10 per page. `showChange`
 *  adds each row's move since the previous list (weekly ranking). */
export function RankingsTable({
  items,
  showChange = false,
}: {
  items: Row[];
  showChange?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const n = items.length;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (r) => r.ticker.toLowerCase().includes(q) || (r.sector ?? "").toLowerCase().includes(q),
    );
  }, [items, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const rows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const grid = cn(
    "grid items-center gap-3",
    showChange
      ? "grid-cols-[40px_64px_minmax(0,1fr)_40px_84px] sm:grid-cols-[56px_88px_minmax(0,1fr)_56px_96px_96px]"
      : "grid-cols-[40px_72px_minmax(0,1fr)_84px] sm:grid-cols-[56px_88px_minmax(0,1fr)_96px_96px]",
  );

  return (
    <div>
      <Input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setPage(0);
        }}
        placeholder="Filter by ticker or sector…"
        aria-label="Filter by ticker or sector"
        className="mb-5 sm:max-w-xs"
      />
      {rows.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">Nothing matches “{query.trim()}”.</p>
      ) : (
        <div className="text-[15px]">
          <div className={cn(grid, "pb-2 text-xs uppercase tracking-[0.05em] text-ink-muted")}>
            <span>Rank</span>
            <span>Stock</span>
            <span>Sector</span>
            {showChange && <span className="text-right">Move</span>}
            <span className="hidden text-right sm:block">Standing</span>
            <span className="text-right">Tier</span>
          </div>
          {rows.map((r) => (
            <Link
              key={r.ticker}
              to={`/stocks/${r.ticker}`}
              className={cn(grid, "row-link border-t border-line py-3.5")}
            >
              <span className="num text-ink-muted">{String(r.rank).padStart(2, "0")}</span>
              <span className="ticker">{r.ticker}</span>
              <span className="truncate text-ink-secondary">{r.sector ?? "—"}</span>
              {showChange && (
                <span className="text-right">
                  <RankChange rank={r.rank} previous={r.previous_rank} />
                </span>
              )}
              <span className="num hidden text-right sm:block">Top {topPercent(r.rank, n)}%</span>
              <span className="text-right">
                <TierLabel tier={tierOf(r.rank, n)} />
              </span>
            </Link>
          ))}
        </div>
      )}
      {pageCount > 1 && <Pager page={safePage + 1} pageCount={pageCount} onPage={(p) => setPage(p - 1)} />}
    </div>
  );
}
