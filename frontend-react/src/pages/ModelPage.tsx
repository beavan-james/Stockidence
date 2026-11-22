import { useEffect } from "react";

import { LeadFigure, PageHero, Section, Stat, Steps } from "@/components/layout/Page";
import { ExcessBars } from "@/components/ranking/ModelCharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview } from "@/hooks/queries";
import { featureMeta } from "@/lib/features";
import { quarterLabel, snapshotLabel } from "@/lib/tiers";
import { leadTone } from "@/lib/utils";
import type { ModelValidation } from "@/types/api";

const pct = (v: number | null, sign = false) =>
  v == null ? "—" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(1)}%`;

const STEPS = [
  {
    title: "Snapshot every stock each quarter",
    body: "At each quarter end the model reads 13 inputs per stock: momentum (3- and 12-month returns, trend, distance from the 52-week high), risk (price swing, drawdown, daily range) and fundamentals from the latest filing as of that date (returns on equity and assets, free cash flow, leverage, liquidity, cash).",
  },
  {
    title: "Learn what the winners looked like",
    body: "An XGBoost ranking model (rank:ndcg) is trained on every past quarter since 2012 to put the stocks that went on to return the most at the top of each quarter's list. It never predicts a price, only an order.",
  },
  {
    title: "Test it the honest way",
    body: "Walk-forward: for each quarter from 2019, the model is trained only on quarters before it, then its picks are scored against what actually happened. That is the track record above.",
  },
  {
    title: "Retrain and re-rank quarterly",
    body: "On the first day of each quarter the data is refreshed, the model is retrained on all history, and the newest quarter's stocks are ranked. Each ranking is kept, so a stock's movement can be followed over time.",
  },
];

const pp = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)} pp`;

/** Walk-forward ranking quality from the latest retrain (mart.model_validation). */
function RankingQuality({ v }: { v: ModelValidation }) {
  const heads = [
    { label: "Top 10", excess: v.top10_excess, t: v.top10_t, hit: v.top10_hit },
    { label: "Top 25", excess: v.top25_excess, t: v.top25_t, hit: v.top25_hit },
    { label: "Top fifth", excess: v.topq_excess, t: v.topq_t, hit: v.topq_hit },
  ];
  return (
    <Section title="Ranking quality">
      <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <LeadFigure value={`${v.rank_ic >= 0 ? "+" : "−"}${Math.abs(v.rank_ic).toFixed(3)}`} />
          <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
            Rank IC: the correlation between the model's order and the order stocks actually
            finished in, pooled over {v.quarters} quarters. 0 is a random order.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
            <Stat
              value={`${Math.round(v.precision10 * 100)}%`}
              label={`of the top 10 finished in the real top 10 (random ${Math.round(v.precision10_random * 100)}%)`}
            />
            <Stat
              value={`${Math.round(v.precision25 * 100)}%`}
              label={`of the top 25 finished in the real top 25 (random ${Math.round(v.precision25_random * 100)}%)`}
            />
          </div>
        </div>
        <div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Picks</th>
                <th className="text-right">Lead over list</th>
                <th className="text-right">Quarters ahead</th>
                <th className="text-right">t-stat</th>
              </tr>
            </thead>
            <tbody>
              {heads.map((h) => (
                <tr key={h.label}>
                  <td>{h.label}</td>
                  <td className={`num text-right font-medium ${leadTone(h.excess >= 0)}`}>{pp(h.excess)}</td>
                  <td className="num text-right text-ink-secondary">{Math.round(h.hit * 100)}%</td>
                  <td className="num text-right text-ink-secondary">{h.t.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-xs leading-relaxed text-ink-muted">
            {v.test_rows.toLocaleString("en-US")} stock-quarters tested; trained on{" "}
            {v.train_rows.toLocaleString("en-US")} rows across {v.train_tickers} stocks,{" "}
            {snapshotLabel(v.train_first)} to {snapshotLabel(v.train_last)}.
          </p>
        </div>
      </div>
    </Section>
  );
}

export function ModelPage() {
  const overview = useModelOverview();

  useEffect(() => {
    document.title = "Quarterly model | Stockidence";
  }, []);

  const o = overview.data;
  const quarters = [...(o?.track_record ?? [])].reverse();

  return (
    <div>
      <PageHero
        link={{ to: "/", label: "← This quarter's list" }}
        title={
          <>
            Ranked, not predicted. <span className="text-accent">Tested before it's trusted.</span>
          </>
        }
        lede="Stocks ordered by how likely they are to beat the rest of the list next quarter."
      />

      <Section title="Track record">
        {overview.isPending ? (
          <Skeleton className="h-64" />
        ) : !o || o.summary.quarters === 0 ? (
          <p className="text-ink-secondary">The track record is published with the next model retrain.</p>
        ) : (
          <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <LeadFigure value={pct(o.summary.avg_excess_vs_spx, true).replace("%", "")} unit="pp" />
              <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                Average quarterly lead of the model's top 20 picks over the S&amp;P 500, across{" "}
                {o.summary.quarters} walk-forward quarters.
              </p>
              <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
                <Stat value={`${Math.round((o.summary.hit_rate_vs_spx ?? 0) * 100)}%`} label="of quarters beat the index" />
                <Stat value={o.summary.quarters} label="quarters tested" />
              </div>
              <div className="mt-7">
                <ExcessBars quarters={o.track_record} height={96} />
              </div>
            </div>
            <div className="max-h-[30rem] overflow-y-auto no-scrollbar">
              <table className="data-table">
                <thead className="sticky top-0 bg-bg">
                  <tr>
                    <th>Quarter</th>
                    <th className="text-right">Top 20</th>
                    <th className="text-right">S&amp;P 500</th>
                    <th className="text-right">Whole list</th>
                    <th className="text-right">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {quarters.map((q) => {
                    const lead =
                      q.top20_return != null && q.spx_return != null ? q.top20_return - q.spx_return : null;
                    return (
                      <tr key={q.quarter}>
                        <td>
                          {quarterLabel(q.quarter)}
                          {q.source === "live" && <span className="ml-2 text-xs text-accent">live</span>}
                        </td>
                        <td className="num text-right">{pct(q.top20_return, true)}</td>
                        <td className="num text-right text-ink-secondary">{pct(q.spx_return, true)}</td>
                        <td className="num text-right text-ink-secondary">{pct(q.universe_return, true)}</td>
                        <td className={`num text-right font-medium ${leadTone(lead != null && lead >= 0)}`}>
                          {lead == null ? "—" : `${lead >= 0 ? "+" : "−"}${Math.abs(lead * 100).toFixed(1)} pp`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      {o?.validation && <RankingQuality v={o.validation} />}

      {o && o.weights.length > 0 && (
        <Section title="What it pays attention to">
          <div className="grid gap-x-10 sm:grid-cols-2">
            {o.weights.map((w) => {
              const meta = featureMeta(w.feature);
              return (
                <div key={w.feature} className="bar-target border-t border-line py-3.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-[15px]">{meta.label}</span>
                    <span className="num text-ink-secondary">{Math.round(w.share * 100)}%</span>
                  </div>
                  <div className="mt-2 h-[6px] bg-white/[0.06]">
                    <div className="bar h-full" style={{ width: `${(w.share / o.weights[0].share) * 100}%` }} />
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">
                    {meta.group} · {meta.help}
                  </p>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      <Section title="How it works">
        <Steps steps={STEPS} />
        <p className="mt-8 max-w-2xl text-sm leading-relaxed text-ink-muted">
          Limits worth knowing: four new data points a year means slow feedback; past quarters don't
          guarantee future ones; and the list covers a fixed universe of mostly large-cap US stocks, not the whole
          market.
        </p>
      </Section>
    </div>
  );
}
