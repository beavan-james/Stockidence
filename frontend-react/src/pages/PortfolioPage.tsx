import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import { HoldingSparkline } from "@/components/portfolio/HoldingSparkline";
import { TickerAutocomplete } from "@/components/layout/TickerAutocomplete";
import { Skeleton } from "@/components/ui/skeleton";
import {
  addHolding,
  removeFromPortfolio,
  updateHolding,
  usePortfolio,
  type Holding,
} from "@/hooks/portfolio";
import { usePriceHistory, useQuote } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import { Pencil, Plus, X } from "lucide-react";

function fmtMoney(v: number | null, digits = 2): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function PnL({ value, pct }: { value: number | null; pct: number | null }) {
  if (value == null) return <span className="num text-sm text-ink-muted">—</span>;
  const up = value >= 0;
  return (
    <span className={cn("num text-sm font-medium", up ? "text-gain" : "text-loss")}>
      {up ? "+" : ""}
      {fmtMoney(value)}
      {pct != null && isFinite(pct) && (
        <span className="ml-1 text-xs">
          ({up ? "+" : ""}
          {pct.toFixed(2)}%)
        </span>
      )}
    </span>
  );
}

function HoldingCard({ holding }: { holding: Holding }) {
  const { symbol, shares, avgCost } = holding;
  const quote = useQuote(symbol);
  const history = usePriceHistory(symbol, 12);
  const [editing, setEditing] = useState(false);
  const [editShares, setEditShares] = useState("");
  const [editCost, setEditCost] = useState("");

  const closes = useMemo(
    () => (history.data ?? []).map((b) => b.close),
    [history.data],
  );
  const lastClose = closes[closes.length - 1] ?? null;
  const prevBarClose = closes[closes.length - 2] ?? null;

  // Live quote first, latest weekly close as fallback so market value
  // shows for every holding with price history, quote or not.
  const price = quote.data?.price ?? lastClose;
  const prevClose = quote.data?.prev_close ?? prevBarClose;
  const dayPct =
    price != null && prevClose ? ((price - prevClose) / prevClose) * 100 : null;

  const hasPosition = shares > 0 && avgCost > 0;
  const marketValue = price != null && shares > 0 ? price * shares : null;
  const costBasis = shares > 0 && avgCost > 0 ? shares * avgCost : null;
  const pnl = marketValue != null && costBasis != null ? marketValue - costBasis : null;
  const pnlPct = pnl != null && costBasis ? (pnl / costBasis) * 100 : null;

  function startEdit() {
    setEditShares(shares ? String(shares) : "");
    setEditCost(avgCost ? String(avgCost) : "");
    setEditing(true);
  }

  function saveEdit() {
    updateHolding(symbol, Number(editShares) || 0, Number(editCost) || 0);
    setEditing(false);
  }

  return (
    <div className="space-y-3 border-b border-line/60 pb-4">
      <div className="flex items-center justify-between gap-2">
          <Link
            to={`/stocks/${symbol}`}
            className="num text-sm font-semibold hover:text-accent"
          >
            {symbol}
          </Link>
          <div className="flex items-center gap-1">
            <button
              onClick={editing ? saveEdit : startEdit}
              className="rounded p-1 text-ink-muted transition-colors hover:text-ink"
              aria-label={editing ? `Save ${symbol}` : `Edit ${symbol}`}
            >
              {editing ? (
                <span className="px-1 text-xs font-medium text-accent">Save</span>
              ) : (
                <Pencil className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              onClick={() => removeFromPortfolio(symbol)}
              className="rounded p-1 text-ink-muted transition-colors hover:text-red-400"
              aria-label={`Remove ${symbol}`}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <HoldingSparkline values={closes} />

        <div className="flex items-baseline justify-between gap-2">
          {price != null ? (
            <span className="num text-lg font-semibold">${price.toFixed(2)}</span>
          ) : quote.isPending ? (
            <Skeleton className="h-6 w-20" />
          ) : (
            <span className="text-sm text-ink-muted">—</span>
          )}
          {dayPct != null && (
            <span className={cn("num text-xs", dayPct >= 0 ? "text-gain" : "text-loss")}>
              {dayPct >= 0 ? "+" : ""}
              {dayPct.toFixed(2)}% today
            </span>
          )}
        </div>

        {editing ? (
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1 text-xs text-ink-muted">
              Shares
              <input
                type="number"
                min="0"
                step="any"
                value={editShares}
                onChange={(e) => setEditShares(e.target.value)}
                placeholder="0"
                className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
              />
            </label>
            <label className="space-y-1 text-xs text-ink-muted">
              Avg cost ($)
              <input
                type="number"
                min="0"
                step="any"
                value={editCost}
                onChange={(e) => setEditCost(e.target.value)}
                placeholder="0.00"
                className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
              />
            </label>
          </div>
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-ink-muted">Shares</dt>
            <dd className="num text-right">{shares > 0 ? shares : "—"}</dd>
            <dt className="text-ink-muted">Avg cost</dt>
            <dd className="num text-right">
              {avgCost > 0 ? fmtMoney(avgCost) : "—"}
            </dd>
            <dt className="text-ink-muted">Market value</dt>
            <dd className="num text-right">{fmtMoney(marketValue)}</dd>
            <dt className="text-ink-muted">P&amp;L</dt>
            <dd className="text-right">
              {hasPosition ? <PnL value={pnl} pct={pnlPct} /> : <span className="text-ink-muted">—</span>}
            </dd>
          </dl>
        )}
    </div>
  );
}

function AddHoldingForm() {
  const [symbol, setSymbol] = useState("");
  const [shares, setShares] = useState("");
  const [cost, setCost] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const clean = symbol.trim().toUpperCase();
    if (!clean) return;
    addHolding(clean, Number(shares) || 0, Number(cost) || 0);
    setSymbol("");
    setShares("");
    setCost("");
  }

  const inputCls =
    "rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none";

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-start gap-2">
      <TickerAutocomplete
        value={symbol}
        onValueChange={setSymbol}
        onPick={(picked) => {
          // Picking a suggestion fills the field without submitting, so
          // shares/cost can still be entered before adding the holding.
          setSymbol(picked);
        }}
        placeholder="Ticker (e.g. AAPL)"
        ariaLabel="Holding ticker search"
        className="w-56"
      />
      <input
        type="number"
        min="0"
        step="any"
        value={shares}
        onChange={(e) => setShares(e.target.value)}
        placeholder="Shares"
        className={cn(inputCls, "w-28")}
      />
      <input
        type="number"
        min="0"
        step="any"
        value={cost}
        onChange={(e) => setCost(e.target.value)}
        placeholder="Avg cost ($)"
        className={cn(inputCls, "w-32")}
      />
      <button
        type="submit"
        disabled={!symbol.trim()}
        className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink-secondary transition-colors hover:border-accent/30 hover:text-ink disabled:opacity-40"
      >
        <Plus className="h-4 w-4" />
        Add holding
      </button>
    </form>
  );
}

function usePortfolioMarket(symbols: string[]) {
  // One query per holding; hooks can't loop, so cap the fan-out.
  // Each slot pairs the live quote with a short price history so market
  // value resolves from the latest weekly close when no quote is cached.
  const q0 = useQuote(symbols[0]); const h0 = usePriceHistory(symbols[0], 3);
  const q1 = useQuote(symbols[1]); const h1 = usePriceHistory(symbols[1], 3);
  const q2 = useQuote(symbols[2]); const h2 = usePriceHistory(symbols[2], 3);
  const q3 = useQuote(symbols[3]); const h3 = usePriceHistory(symbols[3], 3);
  const q4 = useQuote(symbols[4]); const h4 = usePriceHistory(symbols[4], 3);
  const q5 = useQuote(symbols[5]); const h5 = usePriceHistory(symbols[5], 3);
  const q6 = useQuote(symbols[6]); const h6 = usePriceHistory(symbols[6], 3);
  const q7 = useQuote(symbols[7]); const h7 = usePriceHistory(symbols[7], 3);
  const q8 = useQuote(symbols[8]); const h8 = usePriceHistory(symbols[8], 3);
  const q9 = useQuote(symbols[9]); const h9 = usePriceHistory(symbols[9], 3);
  const q10 = useQuote(symbols[10]); const h10 = usePriceHistory(symbols[10], 3);
  const q11 = useQuote(symbols[11]); const h11 = usePriceHistory(symbols[11], 3);
  const quotes = [q0, q1, q2, q3, q4, q5, q6, q7, q8, q9, q10, q11];
  const hists = [h0, h1, h2, h3, h4, h5, h6, h7, h8, h9, h10, h11];
  return symbols.map((_, i) => {
    const closes = (hists[i]?.data ?? []).map((b) => b.close);
    return {
      price: quotes[i]?.data?.price ?? closes[closes.length - 1] ?? null,
      prevClose: quotes[i]?.data?.prev_close ?? closes[closes.length - 2] ?? null,
    };
  });
}

export function PortfolioPage() {
  const { holdings } = usePortfolio();
  const symbols = useMemo(() => holdings.map((h) => h.symbol), [holdings]);
  const market = usePortfolioMarket(symbols);

  useEffect(() => {
    document.title = "Portfolio — Stockidence";
  }, []);

  const rows = useMemo(
    () =>
      holdings.map((h, idx) => {
        const price = market[idx]?.price ?? null;
        const prevClose = market[idx]?.prevClose ?? null;
        const value = price != null && h.shares > 0 ? price * h.shares : 0;
        const cost = h.shares > 0 && h.avgCost > 0 ? h.shares * h.avgCost : 0;
        const dayValue =
          price != null && prevClose && h.shares > 0 ? (price - prevClose) * h.shares : 0;
        return { holding: h, price, value, cost, dayValue };
      }),
    [holdings, market],
  );

  const totalValue = rows.reduce((s, r) => s + r.value, 0);
  const totalCost = rows.reduce((s, r) => s + r.cost, 0);
  const totalPnl = totalValue - totalCost;
  const totalPnlPct = totalCost > 0 ? (totalPnl / totalCost) * 100 : null;
  const dayPnl = rows.reduce((s, r) => s + r.dayValue, 0);

  return (
    <div className="space-y-10">
      <h1 className="title-glow text-xl font-semibold tracking-tight">Portfolio</h1>

      <AddHoldingForm />

      {holdings.length === 0 ? (
        <p className="py-12 text-center text-sm text-ink-muted">
          Your portfolio is empty. Add a holding above to get started —
          shares and avg cost are optional.
        </p>
      ) : (
        <>
          <section className="space-y-4 pt-4">
            <h2 className="text-lg font-semibold tracking-tight">Overview</h2>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1 border-b border-line/60 pb-4">
                <p className="text-xs text-ink-muted">Total value</p>
                <p className="num text-xl font-semibold">{fmtMoney(totalValue, 0)}</p>
              </div>
              <div className="space-y-1 border-b border-line/60 pb-4">
                <p className="text-xs text-ink-muted">Total P&amp;L</p>
                <PnL value={totalCost > 0 ? totalPnl : null} pct={totalPnlPct} />
              </div>
              <div className="space-y-1 border-b border-line/60 pb-4">
                <p className="text-xs text-ink-muted">Day change</p>
                <span
                  className={cn(
                    "num text-xl font-semibold",
                    dayPnl >= 0 ? "text-gain" : "text-loss",
                  )}
                >
                  {dayPnl >= 0 ? "+" : ""}
                  {fmtMoney(dayPnl, 0)}
                </span>
              </div>
            </div>
          </section>

          <section className="space-y-4 pt-4">
            <h2 className="text-lg font-semibold tracking-tight">Allocation</h2>
            <div className="space-y-2.5">
              {totalValue > 0 ? (
                rows.map(({ holding, value }) => {
                  const pct = (value / totalValue) * 100;
                  return (
                    <div key={holding.symbol} className="flex items-center gap-3 text-sm">
                      <span className="num w-16 shrink-0 font-semibold">
                        {holding.symbol}
                      </span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-raised">
                        <div
                          className="h-full rounded-full bg-accent"
                          style={{ width: `${Math.max(pct, 1.5)}%` }}
                        />
                      </div>
                      <span className="num w-14 text-right text-xs text-ink-muted">
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })
              ) : (
                <p className="text-sm text-ink-muted">
                  Add shares and wait for live prices to see allocation.
                </p>
              )}
            </div>
          </section>

          <section className="space-y-4 pt-4">
            <h2 className="text-lg font-semibold tracking-tight">Holdings</h2>
            <div className="grid gap-x-8 md:grid-cols-2 xl:grid-cols-3">
              {holdings.map((h) => (
                <HoldingCard key={h.symbol} holding={h} />
              ))}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
