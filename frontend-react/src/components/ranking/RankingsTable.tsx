import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { TierLabel } from "@/components/ranking/TierLabel";
import { Input } from "@/components/ui/input";
import { Pager } from "@/components/ui/pager";
import { tierOf, topPercent } from "@/lib/tiers";
import type { RankedTicker } from "@/types/api";

const PAGE_SIZE = 25;

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

/** The full ranked list: filter by ticker or sector, 25 per page. `showChange`
 *  adds each row's move since the previous list (weekly ranking). */
export function RankingsTable({
  items,
  limit,
  showChange = false,
}: {
  items: Row[];
  limit?: number;
  showChange?: boolean;
}) {
  const navigate = useNavigate();
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

  const paged = limit == null;
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const rows = paged
    ? filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)
    : items.slice(0, limit);

  return (
    <div>
      {paged && (
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
      )}
      {rows.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">Nothing matches “{query.trim()}”.</p>
      ) : (
        <table className="data-table text-[15px]">
          <thead>
            <tr>
              <th className="w-14">Rank</th>
              <th className="w-24">Stock</th>
              <th>Sector</th>
              {showChange && <th className="w-14 text-right">Move</th>}
              <th className="hidden text-right sm:table-cell">Standing</th>
              <th className="text-right">Tier</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.ticker} onClick={() => void navigate(`/stocks/${r.ticker}`)} className="row-link">
                <td className="num py-3.5 text-ink-muted">{String(r.rank).padStart(2, "0")}</td>
                <td className="ticker py-3.5">{r.ticker}</td>
                <td className="py-3.5 text-ink-secondary">{r.sector ?? "—"}</td>
                {showChange && (
                  <td className="py-3.5 text-right">
                    <RankChange rank={r.rank} previous={r.previous_rank} />
                  </td>
                )}
                <td className="num hidden py-3.5 text-right sm:table-cell">Top {topPercent(r.rank, n)}%</td>
                <td className="py-3.5 text-right">
                  <TierLabel tier={tierOf(r.rank, n)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {paged && pageCount > 1 && <Pager page={safePage + 1} pageCount={pageCount} onPage={(p) => setPage(p - 1)} />}
    </div>
  );
}
