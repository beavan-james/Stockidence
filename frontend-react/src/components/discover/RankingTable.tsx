import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, type Variants } from "framer-motion";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRankings } from "@/hooks/queries";

const ease = [0.22, 1, 0.36, 1] as const;
const PAGE_SIZE = 20;

const rowVariants: Variants = {
  hidden: { opacity: 0, x: -6 },
  visible: { opacity: 1, x: 0 },
};

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.015 } },
};

export function RankingTable() {
  const navigate = useNavigate();
  const rankings = useRankings();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const items = rankings.data?.items ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (r) =>
        r.ticker.toLowerCase().includes(q) ||
        (r.sector ?? "").toLowerCase().includes(q),
    );
  }, [rankings.data, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const rows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <CardTitle>Model rankings</CardTitle>
          {rankings.data && (
            <span className="text-xs text-ink-muted">
              As of {rankings.data.as_of} · {rankings.data.universe_size} tickers
            </span>
          )}
        </div>
        <p className="pt-1 text-xs text-ink-muted">
          Quarterly ranking model — scores order tickers within the cohort; they are
          not expected returns.
        </p>
      </CardHeader>
      <CardContent className="space-y-3 px-2 pb-2 pt-3">
        <div className="px-3">
          <input
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            placeholder="Search ticker or sector…"
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none sm:max-w-xs"
          />
        </div>
        {rankings.isPending ? (
          <div className="space-y-2 px-3 pb-2">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : rankings.isError ? (
          <p className="px-3 pb-2 text-sm text-ink-muted">Rankings unavailable right now.</p>
        ) : filtered.length === 0 ? (
          <p className="px-3 pb-2 text-sm text-ink-muted">No tickers match “{query.trim()}”.</p>
        ) : (
          <motion.div
            variants={containerVariants}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true, amount: 0.1 }}
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-ink-muted">
                  <th className="w-14 px-3 pb-2 font-normal">Rank</th>
                  <th className="px-3 pb-2 font-normal">Ticker</th>
                  <th className="px-3 pb-2 font-normal">Sector</th>
                  <th className="px-3 pb-2 text-right font-normal">Score</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <motion.tr
                    key={r.ticker}
                    variants={rowVariants}
                    transition={{ duration: 0.35, ease }}
                    className="cursor-pointer border-t border-line/60 transition-colors hover:bg-raised"
                    onClick={() => void navigate(`/stocks/${r.ticker}`)}
                  >
                    <td className="num px-3 py-2.5 text-ink-secondary">{r.rank}</td>
                    <td className="num px-3 py-2.5 font-semibold">{r.ticker}</td>
                    <td className="px-3 py-2.5 text-ink-secondary">{r.sector ?? "—"}</td>
                    <td className="num px-3 py-2.5 text-right">{r.score?.toFixed(4) ?? "—"}</td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
            {pageCount > 1 && (
              <div className="flex items-center justify-between px-3 py-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  className="rounded-lg border border-line bg-surface px-3 py-1 text-sm text-ink-secondary transition-colors hover:border-accent/30 hover:text-ink disabled:opacity-40"
                >
                  ← Prev
                </button>
                <span className="num text-xs text-ink-muted">
                  Page {safePage + 1} of {pageCount}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                  disabled={safePage >= pageCount - 1}
                  className="rounded-lg border border-line bg-surface px-3 py-1 text-sm text-ink-secondary transition-colors hover:border-accent/30 hover:text-ink disabled:opacity-40"
                >
                  Next →
                </button>
              </div>
            )}
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
