import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { usePortfolio, addToPortfolio, removeFromPortfolio } from "@/hooks/portfolio";
import { useQuote } from "@/hooks/queries";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { Plus, X } from "lucide-react";

function PortfolioTicker({ symbol }: { symbol: string }) {
  const quote = useQuote(symbol);

  const change =
    quote.data && quote.data.price != null && quote.data.prev_close != null
      ? ((quote.data.price - quote.data.prev_close) / quote.data.prev_close) * 100
      : null;

  return (
    <div className="group flex items-center justify-between gap-4 rounded-lg border border-line bg-surface px-4 py-3 transition-colors hover:border-accent/30">
      <Link to={`/stocks/${symbol}`} className="flex flex-1 items-center gap-3">
        <span className="num text-sm font-semibold">{symbol}</span>
        {quote.data && quote.data.price != null ? (
          <>
            <span className="num text-sm">${quote.data.price.toFixed(2)}</span>
            {change != null && (
              <span className={cn("num text-xs", change >= 0 ? "text-emerald-400" : "text-red-400")}>
                {change >= 0 ? "+" : ""}
                {change.toFixed(2)}%
              </span>
            )}
          </>
        ) : quote.isPending ? (
          <Skeleton className="h-4 w-20" />
        ) : null}
      </Link>
      <button
        onClick={() => removeFromPortfolio(symbol)}
        className="rounded p-1 text-ink-muted opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
        aria-label={`Remove ${symbol}`}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function AddTickerForm() {
  const [value, setValue] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const symbol = value.trim().toUpperCase();
    if (!symbol) return;
    addToPortfolio(symbol);
    setValue("");
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Add ticker (e.g. AAPL)"
        className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
      />
      <button
        type="submit"
        disabled={!value.trim()}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink-secondary transition-colors hover:border-accent/30 hover:text-ink disabled:opacity-40"
      >
        <Plus className="h-4 w-4" />
        Add
      </button>
    </form>
  );
}

export function PortfolioPage() {
  const { tickers } = usePortfolio();

  useEffect(() => {
    document.title = "Portfolio — Stockidence";
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold tracking-tight">Portfolio</h1>

      <AddTickerForm />

      {tickers.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-ink-muted">
            Your portfolio is empty. Add a ticker above to get started.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {tickers.map((t) => (
            <PortfolioTicker key={t} symbol={t} />
          ))}
        </div>
      )}
    </div>
  );
}
