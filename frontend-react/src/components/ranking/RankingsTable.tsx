import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { TierLabel } from "@/components/ranking/TierLabel";
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
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
          placeholder="Filter by ticker or sector…"
          className="mb-3 w-full rounded-lg border border-line bg-transparent px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent/50 focus:outline-none sm:max-w-xs"
        />
      )}
      {rows.length === 0 ? (
        <p className="py-4 text-sm text-ink-muted">Nothing matches “{query.trim()}”.</p>
      ) : (
        <table className="w-full text-[15px]">
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.ticker}
                onClick={() => void navigate(`/stocks/${r.ticker}`)}
                className="cursor-pointer border-t border-line transition-colors hover:bg-white/[0.025]"
              >
                <td className="num w-14 py-3.5 pl-1 text-ink-muted">{String(r.rank).padStart(2, "0")}</td>
                <td className="w-24 py-3.5 font-semibold tracking-wide">{r.ticker}</td>
                <td className="py-3.5 text-ink-secondary">{r.sector ?? "—"}</td>
                {showChange && (
                  <td className="w-14 py-3.5 pr-3 text-right">
                    <RankChange rank={r.rank} previous={r.previous_rank} />
                  </td>
                )}
                <td className="num hidden py-3.5 pr-5 text-right sm:table-cell">
                  Top {topPercent(r.rank, n)}%
                </td>
                <td className="py-3.5 text-right">
                  <TierLabel tier={tierOf(r.rank, n)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {paged && pageCount > 1 && (
        <div className="flex items-center justify-between pt-4 text-sm">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
            className="rounded-lg border border-line px-3 py-1 text-ink-secondary hover:text-ink disabled:opacity-40"
          >
            ← Prev
          </button>
          <span className="num text-xs text-ink-muted">
            Page {safePage + 1} of {pageCount}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={safePage >= pageCount - 1}
            className="rounded-lg border border-line px-3 py-1 text-ink-secondary hover:text-ink disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
