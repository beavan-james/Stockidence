import { useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useNews } from "@/hooks/queries";
import { useDebounced } from "@/hooks/useDebounced";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

function sentimentStyle(label: string): string {
  const l = label.toLowerCase();
  if (l.includes("bullish")) return "text-gain border-gain/30 bg-gain/5";
  if (l.includes("bearish")) return "text-loss border-loss/30 bg-loss/5";
  return "text-ink-secondary border-line bg-raised";
}

function Pager({
  page,
  pageCount,
  onPage,
}: {
  page: number;
  pageCount: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-3 pt-4 text-xs text-ink-muted">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="rounded-lg border border-line px-3 py-1.5 transition-colors enabled:hover:bg-raised disabled:opacity-40"
      >
        ← Prev
      </button>
      <span className="num">
        Page {page} / {pageCount}
      </span>
      <button
        type="button"
        disabled={page >= pageCount}
        onClick={() => onPage(page + 1)}
        className="rounded-lg border border-line px-3 py-1.5 transition-colors enabled:hover:bg-raised disabled:opacity-40"
      >
        Next →
      </button>
    </div>
  );
}

/** Market news with server-side ticker filter and paging. */
export function NewsTable() {
  const [tickerQuery, setTickerQuery] = useState("");
  const [page, setPage] = useState(1);
  const filter = useDebounced(tickerQuery.trim());

  const { data, isLoading, isFetching } = useNews({
    ticker: filter || undefined,
    page,
    pageSize: PAGE_SIZE,
  });

  return (
    <Card className="bg-surface/60 backdrop-blur-sm">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>News &amp; sentiment</CardTitle>
            <p className="mt-0.5 text-xs text-ink-muted">
              {data ? `${data.total.toLocaleString()} articles` : "—"}
              {isFetching && !isLoading && " · loading…"}
            </p>
          </div>
          <Input
            value={tickerQuery}
            onChange={(e) => {
              setTickerQuery(e.target.value.toUpperCase());
              setPage(1);
            }}
            placeholder="Filter by ticker…"
            aria-label="Filter news by ticker"
            className="num w-44"
          />
        </div>
      </CardHeader>
      <CardContent className="px-2 pb-4 pt-2">
        {isLoading ? (
          <div className="space-y-2 p-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-10" />
            ))}
          </div>
        ) : (
          <ul className="divide-y divide-line/60">
            {data?.items.length === 0 && (
              <li className="px-3 py-8 text-center text-sm text-ink-muted">
                No articles match “{filter}”.
              </li>
            )}
            {data?.items.map((n) => (
              <li key={n.url} className="group px-3 py-2.5 transition-colors hover:bg-raised/60">
                <a href={n.url} target="_blank" rel="noreferrer" className="block space-y-1">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm font-medium leading-snug group-hover:text-accent-strong">
                      {n.title}
                    </p>
                    <span
                      className={cn(
                        "shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                        sentimentStyle(n.overall_sentiment_label),
                      )}
                    >
                      {n.overall_sentiment_label.replace("Somewhat-", "S·")}
                    </span>
                  </div>
                  <p className="num text-[11px] text-ink-muted">
                    {n.time_published} · {n.source}
                    {n.sentiment_tickers && ` · ${n.sentiment_tickers}`}
                  </p>
                </a>
              </li>
            ))}
          </ul>
        )}

        {data && data.page_count > 1 && (
          <Pager page={data.page} pageCount={data.page_count} onPage={setPage} />
        )}
      </CardContent>
    </Card>
  );
}
