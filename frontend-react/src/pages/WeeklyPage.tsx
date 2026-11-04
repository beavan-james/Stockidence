import { useEffect } from "react";
import { Link } from "react-router-dom";

import { LeadFigure, PageHero, Section, Stat } from "@/components/layout/Page";
import { WeeklyExcessBars } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { useWeekly } from "@/hooks/queries";
import { dayLabel } from "@/lib/tiers";
import { QUIET_LINK, cn } from "@/lib/utils";
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

  useEffect(() => {
    document.title = "Stockidence | Stocks of the week";
  }, []);

  const d = weekly.data;
  const items = d?.items ?? [];
  const n = items.length;

  return (
    <div>
      <PageHero
        eyebrow="Weekly ranking model"
        link={{ to: "/week/method", label: "How the model works →" }}
        loading={weekly.isPending}
        title={
          d?.week_of ? (
            <>
              Ten stocks for the week of <em className="not-italic text-accent">{dayLabel(d.week_of)}.</em>
            </>
          ) : (
            <>
              The first weekly list lands <em className="not-italic text-accent">Friday after the close.</em>
            </>
          )
        }
        lede={
          <>
            Every Friday after the close{n ? `, ${n}` : ""} US stocks are re-ranked by how likely they are to beat the
            rest of the list over the coming week, bought at Monday's open and sold at Friday's close.
            {d?.as_of ? ` Built from prices to ${dayLabel(d.as_of)}.` : ""}
          </>
        }
      >
        {weekly.isError && <p className="mt-10 text-sm text-ink-muted">This week's list is unavailable right now.</p>}
      </PageHero>

      {n > 0 && (
        <div className={cn(d?.previous && "grid gap-x-12 lg:grid-cols-[1.55fr_1fr]")}>
          <Section
            title="The top 10"
            aside={
              <a href="#all" className={QUIET_LINK}>
                View all {n} ↓
              </a>
            }
          >
            <RankingsTable items={items} limit={10} showChange={d?.previous != null} />
          </Section>
          {d?.previous && <LastWeek previous={d.previous} />}
        </div>
      )}

      {d?.backtest && <Backtest backtest={d.backtest} />}

      {n > 0 && (
        <Section id="all" title={`All ${n} this week`}>
          <RankingsTable items={items} showChange={d?.previous != null} />
        </Section>
      )}
    </div>
  );
}

function LastWeek({ previous }: { previous: NonNullable<WeeklyEnvelope["previous"]> }) {
  const done = previous.top10_return != null;
  return (
    <Section level={3} title="Last week's picks" intro={`Week of ${dayLabel(previous.week_of)}`}>
      {done ? (
        <div className="grid grid-cols-3 gap-5">
          <Stat value={pct(previous.top10_return)} label="top 10" />
          <Stat value={pct(previous.spx_return)} label="S&P 500" />
          <Stat value={pct(previous.universe_return)} label="whole list" />
        </div>
      ) : (
        <p className="text-sm text-ink-muted">Results land Friday after the close.</p>
      )}
      <table className="data-table mt-6">
        <thead>
          <tr>
            <th className="w-14">Rank</th>
            <th>Stock</th>
            <th className="text-right">Return</th>
          </tr>
        </thead>
        <tbody>
          {previous.items.map((r) => (
            <tr key={r.ticker}>
              <td className="num py-2 text-ink-muted">{String(r.rank).padStart(2, "0")}</td>
              <td className="py-2">
                <Link to={`/stocks/${r.ticker}`} className="ticker hover:text-accent">
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
    </Section>
  );
}

function Backtest({ backtest }: { backtest: NonNullable<WeeklyEnvelope["backtest"]> }) {
  const recent = backtest.track.slice(-52);
  return (
    <Section
      title="Backtest"
      aside={
        <Link to="/week/method" className={QUIET_LINK}>
          Method →
        </Link>
      }
    >
      <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        <div>
          {backtest.avg_excess_vs_spx != null && (
            <>
              <LeadFigure value={pp(backtest.avg_excess_vs_spx)} unit="pp" />
              <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                Average weekly lead of the top 10 over the S&amp;P 500 in walk-forward testing, before trading costs.
              </p>
            </>
          )}
          <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
            <Stat value={`${Math.round((backtest.hit_rate_vs_spx ?? 0) * 100)}%`} label="of weeks beat the index" />
            <Stat value={backtest.weeks} label="weeks tested" />
          </div>
        </div>
        <div>
          <WeeklyExcessBars weeks={recent} height={110} />
          <p className="mt-2 text-xs text-ink-muted">Top 10 minus S&amp;P 500, last {recent.length} weeks</p>
        </div>
      </div>
    </Section>
  );
}
