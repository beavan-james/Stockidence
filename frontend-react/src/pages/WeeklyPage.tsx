import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { WeeklyExcessBars } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { Skeleton } from "@/components/ui/skeleton";
import { useWeekly } from "@/hooks/queries";
import { dayLabel } from "@/lib/tiers";
import type { WeeklyEnvelope } from "@/types/api";

/** "+1.2%" / "−0.4%" for a fractional return; "—" when unknown. */
function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)}%`;
}

/** "+0.31 pp" for a fractional lead. */
function pp(v: number, digits = 2): string {
  return `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(digits)}`;
}

export function WeeklyPage() {
  const weekly = useWeekly();
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    document.title = "Stockidence | Stocks of the week";
  }, []);

  const d = weekly.data;
  const items = d?.items ?? [];
  const n = items.length;

  return (
    <div>
      <section className="hero-glow pb-14">
        <p className="pt-10 text-xs uppercase tracking-[0.14em] text-ink-secondary">Weekly ranking model</p>
        {weekly.isPending ? (
          <Skeleton className="mt-5 h-40 max-w-3xl" />
        ) : d?.week_of ? (
          <h1 className="mt-4 max-w-4xl font-medium text-5xl leading-[1.02] tracking-tight sm:text-6xl">
            Ten stocks for the week of <em className="not-italic text-accent">{dayLabel(d.week_of)}.</em>
          </h1>
        ) : (
          <h1 className="mt-4 max-w-4xl font-medium text-5xl leading-[1.02] tracking-tight sm:text-6xl">
            The first weekly list lands <em className="not-italic text-accent">Friday after the close.</em>
          </h1>
        )}
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-secondary">
          Every Friday after the close{n ? `, ${n}` : ""} US stocks are re-ranked by how likely they are to beat
          the rest of the list over the coming week, bought at Monday's open and sold at Friday's close.
          {d?.as_of ? ` Built from prices to ${dayLabel(d.as_of)}.` : ""}
        </p>
        {weekly.isError && <p className="mt-10 text-sm text-ink-muted">This week's list is unavailable right now.</p>}
      </section>

      {n > 0 && (
        <section className="grid gap-12 pb-16 lg:grid-cols-[1.55fr_1fr]">
          <div>
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <h2 className="font-medium text-4xl tracking-tight">The top 10</h2>
              <a
                href="#all"
                onClick={() => setShowAll(true)}
                className="whitespace-nowrap text-sm text-ink-secondary hover:text-ink"
              >
                View all {n} ↓
              </a>
            </div>
            <RankingsTable items={items} limit={10} showChange={d?.previous != null} />
          </div>

          <div className="space-y-10">
            {d?.previous && <LastWeek previous={d.previous} />}
            {d?.backtest && <Backtest backtest={d.backtest} />}
          </div>
        </section>
      )}

      {n > 0 && (
        <section id="all" className="scroll-mt-24 pb-10">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="font-medium text-4xl tracking-tight">All {n} this week</h2>
            <button
              onClick={() => setShowAll((v) => !v)}
              className="whitespace-nowrap text-sm text-ink-secondary hover:text-ink"
            >
              {showAll ? "Hide full list ↑" : `Show full list ↓`}
            </button>
          </div>
          {showAll && <RankingsTable items={items} showChange={d?.previous != null} />}
        </section>
      )}
    </div>
  );
}

function LastWeek({ previous }: { previous: NonNullable<WeeklyEnvelope["previous"]> }) {
  const done = previous.top10_return != null;
  return (
    <div className="border-t border-line pt-6">
      <h3 className="font-medium text-2xl">Last week's picks</h3>
      <p className="mt-1 text-sm text-ink-secondary">Week of {dayLabel(previous.week_of)}</p>
      {done ? (
        <div className="mt-5 grid grid-cols-3 gap-5">
          <div>
            <p className="num text-2xl">{pct(previous.top10_return)}</p>
            <p className="text-xs text-ink-muted">top 10</p>
          </div>
          <div>
            <p className="num text-2xl">{pct(previous.spx_return)}</p>
            <p className="text-xs text-ink-muted">S&amp;P 500</p>
          </div>
          <div>
            <p className="num text-2xl">{pct(previous.universe_return)}</p>
            <p className="text-xs text-ink-muted">whole list</p>
          </div>
        </div>
      ) : (
        <p className="mt-4 text-sm text-ink-muted">Results land Friday after the close.</p>
      )}
      <table className="mt-5 w-full text-sm">
        <tbody>
          {previous.items.map((r) => (
            <tr key={r.ticker} className="border-t border-line">
              <td className="num w-10 py-2 text-ink-muted">{String(r.rank).padStart(2, "0")}</td>
              <td className="py-2 font-semibold tracking-wide">
                <Link to={`/stocks/${r.ticker}`} className="hover:text-accent">
                  {r.ticker}
                </Link>
              </td>
              <td
                className={`num py-2 text-right ${
                  r.realized_return == null
                    ? "text-ink-muted"
                    : r.realized_return >= 0
                      ? "text-gain"
                      : "text-loss"
                }`}
              >
                {pct(r.realized_return)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Backtest({ backtest }: { backtest: NonNullable<WeeklyEnvelope["backtest"]> }) {
  const recent = backtest.track.slice(-52);
  return (
    <div className="border-t border-line pt-6">
      <div className="flex items-baseline justify-between">
        <h3 className="font-medium text-2xl">Backtest</h3>
        <Link to="/docs" className="text-sm text-ink-secondary hover:text-ink">
          Method →
        </Link>
      </div>
      {backtest.avg_excess_vs_spx != null && (
        <>
          <p className="num mt-4 font-medium text-6xl leading-none tracking-tight">
            {pp(backtest.avg_excess_vs_spx)}
            <span className="text-3xl"> pp</span>
          </p>
          <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
            Average weekly lead of the top 10 over the S&amp;P 500 in walk-forward testing, before trading costs.
          </p>
        </>
      )}
      <div className="mt-5">
        <WeeklyExcessBars weeks={recent} />
        <p className="mt-2 text-xs text-ink-muted">Last {recent.length} weeks</p>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-5 border-t border-line pt-5">
        <div>
          <p className="num text-2xl">{Math.round((backtest.hit_rate_vs_spx ?? 0) * 100)}%</p>
          <p className="text-xs text-ink-muted">of weeks beat the index</p>
        </div>
        <div>
          <p className="num text-2xl">{backtest.weeks}</p>
          <p className="text-xs text-ink-muted">weeks tested</p>
        </div>
      </div>
    </div>
  );
}
