import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Pager } from "@/components/ui/pager";
import { Skeleton } from "@/components/ui/skeleton";
import { useNews } from "@/hooks/queries";
import { useDebounced } from "@/hooks/useDebounced";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;

/** "Somewhat-Bullish" as plain text, softened green or red by direction. */
function sentiment(label: string): { text: string; tone: string } {
  const l = label.toLowerCase();
  const text = l.replace("-", " ");
  return {
    text: text.charAt(0).toUpperCase() + text.slice(1),
    tone: l.includes("bullish") ? "text-gain/70" : l.includes("bearish") ? "text-loss/70" : "text-ink-muted",
  };
}

/** Market news with server-side headline/date filters and SQL paging. */
export function NewsTable() {
  const [headlineQuery, setHeadlineQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);
  const filter = useDebounced(headlineQuery.trim());

  const { data, isLoading, isFetching } = useNews({
    headline: filter || undefined,
    dateFrom: from || undefined,
    dateTo: to || undefined,
    page,
    pageSize: PAGE_SIZE,
  });

  function resetPage() {
    setPage(1);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
        <div>
          <p className="text-xs text-ink-muted">
            {data ? `${data.total.toLocaleString()} articles` : "Article count unavailable"}
            {isFetching && !isLoading && " · loading…"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="search"
            value={headlineQuery}
            onChange={(e) => {
              setHeadlineQuery(e.target.value);
              resetPage();
            }}
            placeholder="Search headlines"
            aria-label="Search news by headline"
            className="w-64"
          />
          <Input
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => {
              setFrom(e.target.value);
              resetPage();
            }}
            aria-label="News from date"
            className="num w-36"
          />
          <Input
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => {
              setTo(e.target.value);
              resetPage();
            }}
            aria-label="News to date"
            className="num w-36"
          />
        </div>
      </div>
      {isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {data?.items.length === 0 && (
            <li className="py-8 text-center text-sm text-ink-muted">
              {filter ? `No headlines match “${filter}”.` : "No articles in that date range."}
            </li>
          )}
          {data?.items.map((n) => {
            const s = n.overall_sentiment_label ? sentiment(n.overall_sentiment_label) : null;
            return (
              <li key={n.url} className="group py-3">
                <a href={n.url} target="_blank" rel="noopener noreferrer" className="block space-y-1">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-[15px] leading-snug transition-colors group-hover:text-accent">{n.title}</p>
                    {s && <span className={cn("shrink-0 whitespace-nowrap pt-0.5 text-[11px]", s.tone)}>{s.text}</span>}
                  </div>
                  <p className="num text-xs text-ink-muted">
                    {n.time_published} · {n.source}
                    {n.sentiment_tickers && ` · ${n.sentiment_tickers}`}
                  </p>
                </a>
              </li>
            );
          })}
        </ul>
      )}

      {data && data.page_count > 1 && <Pager page={data.page} pageCount={data.page_count} onPage={setPage} />}
    </div>
  );
}
