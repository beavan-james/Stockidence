import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { TierLabel } from "@/components/ranking/TierLabel";
import { Input } from "@/components/ui/input";
import { tierOf } from "@/lib/tiers";
import type { RankedTicker } from "@/types/api";

/**
 * Look a stock up in this quarter's ranking. Searches only the ranked list
 * (client-side, instant); Enter or a click opens the stock's page. `onMatch`
 * hears the highlighted match, so the page can light it up elsewhere.
 */
export function StockLookup({
  items,
  onMatch,
}: {
  items: RankedTicker[];
  onMatch?: (ticker: string | null) => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const n = items.length;

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return [];
    const exact = items.filter((r) => r.ticker === q);
    const prefix = items.filter((r) => r.ticker !== q && r.ticker.startsWith(q));
    return [...exact, ...prefix].slice(0, 6);
  }, [items, query]);

  const open = (ticker: string) => void navigate(`/stocks/${ticker}`);
  const q = query.trim();
  const current = matches[active]?.ticker ?? null;

  useEffect(() => {
    onMatch?.(current);
  }, [current, onMatch]);

  return (
    <div className="relative w-full max-w-sm">
      <Input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, matches.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === "Enter" && matches[active]) {
            open(matches[active].ticker);
          }
        }}
        placeholder="Search by ticker"
        aria-label="Find a ranked stock"
        className="h-12 px-4 text-base"
      />
      {q && (
        <div className="absolute inset-x-0 top-full z-30 mt-2 overflow-hidden rounded-[10px] border border-white/[0.1] bg-black/90 backdrop-blur-md">
          {matches.length === 0 ? (
            <p className="px-4 py-3.5 text-sm text-ink-muted">
              {q.toUpperCase()} isn't in this quarter's ranking.
            </p>
          ) : (
            matches.map((r, i) => (
              <button
                key={r.ticker}
                onMouseEnter={() => setActive(i)}
                onClick={() => open(r.ticker)}
                className={`flex w-full items-center gap-4 px-4 py-3 text-left text-sm ${
                  i === active ? "bg-white/[0.06]" : ""
                }`}
              >
                <span className="w-16 font-semibold">{r.ticker}</span>
                <span className="flex-1 truncate text-ink-secondary">{r.sector ?? "—"}</span>
                <span className="num text-ink-secondary">#{r.rank}</span>
                <TierLabel tier={tierOf(r.rank, n)} />
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
