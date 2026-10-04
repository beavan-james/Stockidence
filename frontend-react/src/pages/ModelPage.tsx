import { useEffect } from "react";
import { Link } from "react-router-dom";

import { ExcessBars } from "@/components/ranking/ModelCharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview } from "@/hooks/queries";
import { featureMeta } from "@/lib/features";
import { quarterLabel, snapshotLabel } from "@/lib/tiers";
import type { ModelValidation } from "@/types/api";

// Sections are separated by a hairline rule, not boxed panels.
const PANEL = "border-t border-line pt-6";

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
    <section className="pb-16">
      <h2 className="font-medium text-4xl tracking-tight">Ranking quality</h2>
      <p className="mt-3 max-w-2xl leading-relaxed text-ink-secondary">
        The same walk-forward test, graded on the whole list rather than one index: how well the
        order matched what actually happened, and how far the head of the list pulled ahead of
        the rest.
      </p>
      <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        <div className={PANEL}>
          <p className="num font-medium text-7xl leading-none tracking-tight">
            {v.rank_ic >= 0 ? "+" : "−"}
            {Math.abs(v.rank_ic).toFixed(3)}
          </p>
          <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
            Rank IC: the correlation between the model's order and the order stocks actually
            finished in, pooled over {v.quarters} quarters. 0 is a random order.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
            <div>
              <p className="num text-3xl">{Math.round(v.precision10 * 100)}%</p>
              <p className="text-xs text-ink-muted">
                of the top 10 finished in the real top 10 (random {Math.round(v.precision10_random * 100)}%)
              </p>
            </div>
            <div>
              <p className="num text-3xl">{Math.round(v.precision25 * 100)}%</p>
              <p className="text-xs text-ink-muted">
                of the top 25 finished in the real top 25 (random {Math.round(v.precision25_random * 100)}%)
              </p>
            </div>
          </div>
        </div>
        <div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wider text-ink-muted">
              <tr>
                <th className="pb-2 font-normal">Picks</th>
                <th className="pb-2 text-right font-normal">Lead over list</th>
                <th className="pb-2 text-right font-normal">Quarters ahead</th>
                <th className="pb-2 text-right font-normal">t-stat</th>
              </tr>
            </thead>
            <tbody>
              {heads.map((h) => (
                <tr key={h.label} className="border-t border-line">
                  <td className="py-3">{h.label}</td>
                  <td
                    className="num py-3 text-right font-medium"
                    style={{ color: h.excess >= 0 ? "var(--color-accent-strong)" : "#8e97ad" }}
                  >
                    {pp(h.excess)}
                  </td>
                  <td className="num py-3 text-right text-ink-secondary">{Math.round(h.hit * 100)}%</td>
                  <td className="num py-3 text-right text-ink-secondary">{h.t.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-xs leading-relaxed text-ink-muted">
            Lead is the picks' average quarterly return minus the whole list's. A t-stat near 2 or
            above is the usual bar for an edge unlikely to be luck. Tested on{" "}
            {v.test_rows.toLocaleString("en-US")} stock-quarters; the model is trained on{" "}
            {v.train_rows.toLocaleString("en-US")} rows across {v.train_tickers} stocks (
            {snapshotLabel(v.train_first)} to {snapshotLabel(v.train_last)}). Measured{" "}
            {snapshotLabel(v.run_at.slice(0, 10))}.
          </p>
        </div>
      </div>
    </section>
  );
}

export function ModelPage() {
  const overview = useModelOverview();

  useEffect(() => {
    document.title = "Model | Stockidence";
  }, []);

  const o = overview.data;
  const quarters = [...(o?.track_record ?? [])].reverse();

  return (
    <div>
      <section className="hero-glow pb-14">
        <p className="pt-10 text-xs uppercase tracking-[0.14em] text-ink-secondary">The model</p>
        <h1 className="mt-4 max-w-4xl font-medium text-5xl leading-[1.02] tracking-tight sm:text-7xl">
          Ranked, not predicted. <em className="not-italic text-accent">Tested before it's trusted.</em>
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-secondary">
          Stockidence orders stocks by how likely they are to beat the rest of the list next
          quarter. Here is how it does that, how it has performed, and what it pays attention to.
        </p>
      </section>

      <section className="pb-16">
        <h2 className="font-medium text-4xl tracking-tight">Track record</h2>
        {overview.isPending ? (
          <Skeleton className="mt-6 h-64" />
        ) : !o || o.summary.quarters === 0 ? (
          <p className="mt-4 text-ink-secondary">
            The track record is published with the next model retrain.
          </p>
        ) : (
          <div className="mt-6 grid gap-8 lg:grid-cols-[1fr_1.4fr]">
            <div className={PANEL}>
              <p className="num font-medium text-7xl leading-none tracking-tight">
                {pct(o.summary.avg_excess_vs_spx, true).replace("%", "")}
                <span className="text-3xl"> pp</span>
              </p>
              <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                Average quarterly lead of the model's top 20 picks over the S&amp;P 500, across{" "}
                {o.summary.quarters} walk-forward quarters.
              </p>
              <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
                <div>
                  <p className="num text-3xl">{Math.round((o.summary.hit_rate_vs_spx ?? 0) * 100)}%</p>
                  <p className="text-xs text-ink-muted">of quarters beat the index</p>
                </div>
                <div>
                  <p className="num text-3xl">{o.summary.quarters}</p>
                  <p className="text-xs text-ink-muted">quarters tested</p>
                </div>
              </div>
              <div className="mt-7">
                <ExcessBars quarters={o.track_record} height={96} />
                <p className="mt-2 text-xs text-ink-muted">Top 20 minus S&amp;P 500, by quarter</p>
              </div>
            </div>
            <div className="max-h-[30rem] overflow-y-auto no-scrollbar">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-bg text-left text-xs uppercase tracking-wider text-ink-muted">
                  <tr>
                    <th className="pb-2 font-normal">Quarter</th>
                    <th className="pb-2 text-right font-normal">Top 20</th>
                    <th className="pb-2 text-right font-normal">S&amp;P 500</th>
                    <th className="pb-2 text-right font-normal">Whole list</th>
                    <th className="pb-2 text-right font-normal">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {quarters.map((q) => {
                    const lead =
                      q.top20_return != null && q.spx_return != null ? q.top20_return - q.spx_return : null;
                    return (
                      <tr key={q.quarter} className="border-t border-line">
                        <td className="py-2.5">
                          {quarterLabel(q.quarter)}
                          {q.source === "live" && <span className="ml-2 text-xs text-accent">live</span>}
                        </td>
                        <td className="num py-2.5 text-right">{pct(q.top20_return, true)}</td>
                        <td className="num py-2.5 text-right text-ink-secondary">{pct(q.spx_return, true)}</td>
                        <td className="num py-2.5 text-right text-ink-secondary">{pct(q.universe_return, true)}</td>
                        <td
                          className="num py-2.5 text-right font-medium"
                          style={{ color: lead != null && lead >= 0 ? "var(--color-accent-strong)" : "#8e97ad" }}
                        >
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
      </section>

      {o?.validation && <RankingQuality v={o.validation} />}

      {o && o.weights.length > 0 && (
        <section className="pb-16">
          <h2 className="font-medium text-4xl tracking-tight">What it pays attention to</h2>
          <p className="mt-3 max-w-2xl leading-relaxed text-ink-secondary">
            A tree model has no fixed weights, so this is the share of a typical stock's score
            explained by each input in the {quarterLabel(o.as_of!)} ranking. Each stock's page shows
            its own breakdown.
          </p>
          <div className="mt-6 grid gap-x-10 sm:grid-cols-2">
            {o.weights.map((w) => {
              const meta = featureMeta(w.feature);
              return (
                <div key={w.feature} className="border-t border-line py-3.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-[15px]">{meta.label}</span>
                    <span className="num text-ink-secondary">{Math.round(w.share * 100)}%</span>
                  </div>
                  <div className="mt-2 h-[6px] overflow-hidden bg-white/[0.06]">
                    <div
                      className="h-full"
                      style={{
                        width: `${(w.share / o.weights[0].share) * 100}%`,
                        background: "linear-gradient(90deg, var(--color-cobalt), var(--color-accent))",
                      }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">
                    {meta.group} · {meta.help}
                  </p>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="pb-10">
        <h2 className="font-medium text-4xl tracking-tight">How it works</h2>
        <ol className="mt-6 grid gap-6 md:grid-cols-2">
          {STEPS.map((s, i) => (
            <li key={s.title} className={PANEL}>
              <span className="num text-sm text-accent">0{i + 1}</span>
              <h3 className="mt-2 font-medium text-2xl">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-secondary">{s.body}</p>
            </li>
          ))}
        </ol>
        <p className="mt-8 max-w-2xl text-sm leading-relaxed text-ink-muted">
          Limits worth knowing: four new data points a year means slow feedback; past quarters don't
          guarantee future ones; and the list covers a fixed universe of mostly large-cap US stocks, not the whole
          market. Not investment advice. The full technical write-up lives in the{" "}
          <Link to="/docs" className="text-accent hover:text-accent-strong">
            documentation
          </Link>
          .
        </p>
      </section>
    </div>
  );
}
