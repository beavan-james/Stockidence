import { useEffect, useMemo } from "react";

import { LeadFigure, PageHero, Section, Stat, Steps } from "@/components/layout/Page";
import { WeeklyExcessBars } from "@/components/ranking/ModelCharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useWeekly } from "@/hooks/queries";
import { FEATURES, featureMeta } from "@/lib/features";
import { snapshotLabel } from "@/lib/tiers";
import { leadTone } from "@/lib/utils";
import type { WeeklyTrackWeek, WeeklyValidation } from "@/types/api";

const pct = (v: number | null) =>
  v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)}%`;

const pp = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(2)} pp`);

const mean = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);

const STEPS = [
  {
    title: "Snapshot every stock each Friday",
    body: "After the close the model reads the same 13 inputs the quarterly model uses: momentum, risk and fundamentals from the latest filing as of that date. Only stocks that landed the week's last close are scored, so a failed price fetch can't rank a stale snapshot.",
  },
  {
    title: "Learn what next week's winners looked like",
    body: "An XGBoost ranking model (rank:ndcg) is trained on every closed week to put the stocks that went on to return the most the following week at the top of each week's list. It never predicts a price, only an order.",
  },
  {
    title: "Test it the honest way",
    body: "Walk-forward: from 2019 the model is refit once a quarter on weeks whose outcome had already closed, then ranks the next 13 weeks, so no week is scored by a model that saw it. That is the track record above.",
  },
  {
    title: "Publish Friday, grade the next Friday",
    body: "Each list is for the coming week: bought at Monday's open and sold at Friday's close, so it never holds over a weekend. The next Friday's run grades that list on what happened, retrains on every closed week and publishes the next one.",
  },
];

/** Average week in each snapshot year: 400 rows of weekly noise don't read as a history. */
function byYear(track: WeeklyTrackWeek[]) {
  const years = new Map<string, WeeklyTrackWeek[]>();
  for (const w of track) {
    const year = w.week.slice(0, 4);
    years.set(year, [...(years.get(year) ?? []), w]);
  }
  return [...years.entries()].reverse().map(([year, weeks]) => {
    const avg = (key: "top10_return" | "spx_return" | "universe_return") =>
      mean(weeks.flatMap((w) => (w[key] == null ? [] : [w[key]])));
    const leads = weeks.flatMap((w) =>
      w.top10_return == null || w.spx_return == null ? [] : [w.top10_return - w.spx_return],
    );
    return {
      year,
      weeks: weeks.length,
      top10: avg("top10_return"),
      spx: avg("spx_return"),
      universe: avg("universe_return"),
      lead: mean(leads),
    };
  });
}

/** One-sample t-stat of the top 10's weekly lead over the S&P 500. */
function spxTStat(track: WeeklyTrackWeek[]): number | null {
  const leads = track.flatMap((w) =>
    w.top10_return == null || w.spx_return == null ? [] : [w.top10_return - w.spx_return],
  );
  const m = mean(leads);
  if (m == null || leads.length < 2) return null;
  const variance = leads.reduce((s, x) => s + (x - m) ** 2, 0) / (leads.length - 1);
  return m / Math.sqrt(variance / leads.length);
}

/** Walk-forward ranking quality from the latest Friday run. */
function RankingQuality({ v, spxT }: { v: WeeklyValidation; spxT: number | null }) {
  const benchmarks = [
    { label: "Whole list", lead: v.top10_excess, hit: v.top10_hit, t: v.top10_t },
    { label: "S&P 500", lead: v.top10_vs_spx, hit: v.top10_vs_spx_hit, t: spxT },
  ];
  return (
    <Section title="Ranking quality">
      <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <LeadFigure value={`${v.rank_ic >= 0 ? "+" : "−"}${Math.abs(v.rank_ic).toFixed(3)}`} />
          <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
            Rank IC: the correlation between the model's order and the order stocks actually
            finished in, averaged over {v.weeks} weeks. 0 is a random order.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
            <Stat value={`${Math.round(v.precision10 * 100)}%`} label="of the top 10 finished in that week's real top 10" />
            <Stat value={`${Math.round(v.precision10_random * 100)}%`} label="what a random list would score" />
          </div>
        </div>
        <div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Top 10 against</th>
                <th className="text-right">Lead per week</th>
                <th className="text-right">Weeks ahead</th>
                <th className="text-right">t-stat</th>
              </tr>
            </thead>
            <tbody>
              {benchmarks.map((b) => (
                <tr key={b.label}>
                  <td>{b.label}</td>
                  <td className={`num text-right font-medium ${leadTone(b.lead != null && b.lead >= 0)}`}>{pp(b.lead)}</td>
                  <td className="num text-right text-ink-secondary">
                    {b.hit == null ? "—" : `${Math.round(b.hit * 100)}%`}
                  </td>
                  <td className="num text-right text-ink-secondary">{b.t == null ? "—" : b.t.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 text-xs leading-relaxed text-ink-muted">
            {v.test_rows.toLocaleString("en-US")} stock-weeks tested; trained on{" "}
            {v.train_rows.toLocaleString("en-US")} rows across {v.train_tickers} stocks,{" "}
            {snapshotLabel(v.train_first)} to {snapshotLabel(v.train_last)}.
          </p>
        </div>
      </div>
    </Section>
  );
}

export function WeeklyMethodPage() {
  const weekly = useWeekly();

  useEffect(() => {
    document.title = "Weekly model | Stockidence";
  }, []);

  const d = weekly.data;
  const backtest = d?.backtest;
  const track = useMemo(() => backtest?.track ?? [], [backtest]);
  const years = useMemo(() => byYear(track), [track]);
  const recent = track.slice(-52);

  return (
    <div>
      <PageHero
        link={{ to: "/week", label: "← This week's list" }}
        title={
          <>
            Re-ranked every Friday. <span className="text-accent">Graded the Friday after.</span>
          </>
        }
        lede="Stocks ordered by how likely they are to beat the rest of the list next week."
      />

      <Section title="Track record">
        {weekly.isPending ? (
          <Skeleton className="h-64" />
        ) : !backtest || backtest.avg_excess_vs_spx == null ? (
          <p className="text-ink-secondary">The track record is published with the first Friday run.</p>
        ) : (
          <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
            <div>
              <LeadFigure value={pp(backtest.avg_excess_vs_spx).replace(" pp", "")} unit="pp" />
              <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                Average weekly lead of the model's top 10 picks over the S&amp;P 500, across{" "}
                {backtest.weeks} walk-forward weeks, before trading costs.
              </p>
              <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
                <Stat value={`${Math.round((backtest.hit_rate_vs_spx ?? 0) * 100)}%`} label="of weeks beat the index" />
                <Stat value={backtest.weeks} label="weeks tested" />
              </div>
              <div className="mt-7">
                <WeeklyExcessBars weeks={recent} height={96} />
              </div>
              {d?.live && d.live.avg_excess_vs_spx != null && (
                <p className="mt-5 border-t border-line pt-5 text-sm leading-relaxed text-ink-secondary">
                  <span className="text-accent">Live</span> so far: {pp(d.live.avg_excess_vs_spx)} a week over{" "}
                  {d.live.weeks} graded {d.live.weeks === 1 ? "list" : "lists"}.
                </p>
              )}
            </div>
            <div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Avg week in</th>
                    <th className="text-right">Top 10</th>
                    <th className="text-right">S&amp;P 500</th>
                    <th className="text-right">Whole list</th>
                    <th className="text-right">Lead</th>
                  </tr>
                </thead>
                <tbody>
                  {years.map((y) => (
                    <tr key={y.year}>
                      <td>{y.year}</td>
                      <td className="num text-right">{pct(y.top10)}</td>
                      <td className="num text-right text-ink-secondary">{pct(y.spx)}</td>
                      <td className="num text-right text-ink-secondary">{pct(y.universe)}</td>
                      <td className={`num text-right font-medium ${leadTone(y.lead != null && y.lead >= 0)}`}>
                        {pp(y.lead)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      {d?.validation && <RankingQuality v={d.validation} spxT={spxTStat(track)} />}

      <Section
        title="What it looks at"
        intro={
          d && d.weights.length > 0
            ? "The same 13 inputs as the quarterly model."
            : !weekly.isPending &&
              "The same 13 inputs as the quarterly model. How much each one counts is published with the next Friday run."
        }
      >
        {weekly.isPending ? (
          <Skeleton className="h-64" />
        ) : d && d.weights.length > 0 ? (
          <div className="grid gap-x-10 sm:grid-cols-2">
            {d.weights.map((w) => {
              const meta = featureMeta(w.feature);
              return (
                <div key={w.feature} className="bar-target border-t border-line py-3.5">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-[15px]">{meta.label}</span>
                    <span className="num text-ink-secondary">{Math.round(w.share * 100)}%</span>
                  </div>
                  <div className="mt-2 h-[6px] bg-white/[0.06]">
                    <div className="bar h-full" style={{ width: `${(w.share / d.weights[0].share) * 100}%` }} />
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">
                    {meta.group} · {meta.help}
                  </p>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="grid gap-x-10 sm:grid-cols-2">
            {Object.entries(FEATURES).map(([feature, meta]) => (
              <div key={feature} className="border-t border-line py-3.5">
                <span className="text-[15px]">{meta.label}</span>
                <p className="mt-1 text-xs text-ink-muted">
                  {meta.group} · {meta.help}
                </p>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="How it works">
        <Steps steps={STEPS} />
        <p className="mt-8 max-w-2xl text-sm leading-relaxed text-ink-muted">
          Limits worth knowing: the backtest deducts no trading costs, and the list changes names every
          week; stocks delisted since 2019 are missing from the test, which flatters absolute returns, so
          read the lead rather than the raw return; and the top 10 can lean heavily on one sector.
        </p>
      </Section>
    </div>
  );
}
