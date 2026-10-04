import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { QuoteBadge } from "@/components/profile/QuoteBadge";
import { DistributionStrip } from "@/components/ranking/DistributionStrip";
import { WeightBars } from "@/components/ranking/ModelCharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview, useRankingDetail, useRankings } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { featureMeta, formatFeature, formatPoints } from "@/lib/features";
import { TIER_COLORS, TIER_NAMES, quarterLabel } from "@/lib/tiers";
import type { FeatureContribution } from "@/types/api";

// Sections are separated by a hairline rule, not boxed panels.
const PANEL = "border-t border-line pt-6";

/** "Strong on momentum, held back by risk" from per-group net contributions. */
function verdict(features: FeatureContribution[]): { title: string; body: string } | null {
  if (features.length === 0) return null;
  const groups = new Map<string, number>();
  for (const f of features) {
    const g = featureMeta(f.feature).group;
    groups.set(g, (groups.get(g) ?? 0) + f.contribution);
  }
  const ranked = [...groups.entries()].sort((a, b) => b[1] - a[1]);
  const best = ranked[0];
  const worst = ranked[ranked.length - 1];
  const lift = [...features].sort((a, b) => b.contribution - a.contribution).filter((f) => f.contribution > 0);
  const drag = [...features].sort((a, b) => a.contribution - b.contribution).filter((f) => f.contribution < 0);
  const title =
    best[1] > 0 && worst[1] < 0
      ? `Strong on ${best[0].toLowerCase()}, held back by ${worst[0].toLowerCase()}`
      : best[1] > 0
        ? `Lifted across the board, led by ${best[0].toLowerCase()}`
        : `Held back across the board, most by ${worst[0].toLowerCase()}`;
  const parts: string[] = [];
  if (lift.length) {
    parts.push(
      `${lift
        .slice(0, 2)
        .map((f) => featureMeta(f.feature).label.toLowerCase())
        .join(" and ")} did the most lifting`,
    );
  }
  if (drag.length) {
    parts.push(`${featureMeta(drag[0].feature).label.toLowerCase()} pulled hardest the other way`);
  }
  const body = parts.length ? `${parts.join("; ")}.` : "";
  return { title, body: body.charAt(0).toUpperCase() + body.slice(1) };
}

function Contributions({ features }: { features: FeatureContribution[] }) {
  const max = Math.max(...features.map((f) => Math.abs(f.contribution)), 1e-9);
  return (
    <div className="mt-6">
      <div className="hidden grid-cols-[minmax(0,1.35fr)_6.5rem_6.5rem_minmax(0,1.2fr)_3.5rem] gap-4 pb-2 text-xs uppercase tracking-wider text-ink-muted md:grid">
        <span>Input</span>
        <span>This stock</span>
        <span>List median</span>
        <span className="text-center">Pulls down · pushes up</span>
        <span className="text-right">Pts</span>
      </div>
      {features.map((f) => {
        const meta = featureMeta(f.feature);
        const w = (Math.abs(f.contribution) / max) * 50;
        const up = f.contribution >= 0;
        return (
          <div
            key={f.feature}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-t border-line py-3 md:grid-cols-[minmax(0,1.35fr)_6.5rem_6.5rem_minmax(0,1.2fr)_3.5rem]"
            title={meta.help}
          >
            <div>
              <div className="text-[15px]">{meta.label}</div>
              <div className="text-xs text-ink-muted">
                {meta.group}
                <span className="num md:hidden">
                  {" · "}
                  {formatFeature(f.feature, f.value)} vs median {formatFeature(f.feature, f.median)}
                </span>
              </div>
            </div>
            <div className="num hidden text-[15px] md:block">{formatFeature(f.feature, f.value)}</div>
            <div className="num hidden text-sm text-ink-muted md:block">{formatFeature(f.feature, f.median)}</div>
            <div className="relative col-span-2 h-3.5 md:col-span-1">
              <div className="absolute inset-y-[-6px] left-1/2 w-px bg-white/20" />
              <div
                className={`absolute inset-y-0 ${up ? "" : "bg-[#3a4256]"}`}
                style={{
                  left: up ? "50%" : `${50 - w}%`,
                  width: `${w}%`,
                  background: up ? "linear-gradient(90deg, var(--color-cobalt), var(--color-accent))" : undefined,
                }}
              />
            </div>
            <div
              className="num col-start-2 row-start-1 text-right text-[15px] font-medium md:col-start-auto md:row-start-auto"
              style={{ color: up ? "var(--color-accent-strong)" : "#8e97ad" }}
            >
              {formatPoints(f.contribution)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StockPage() {
  const symbol = useParams().symbol?.toUpperCase();
  const detail = useRankingDetail(symbol);
  const rankings = useRankings();
  const overview = useModelOverview();

  useEffect(() => {
    document.title = symbol ? `${symbol} | Stockidence` : "Stockidence";
  }, [symbol]);

  if (detail.isPending) {
    return (
      <div className="space-y-6 pt-12">
        <Skeleton className="h-28 w-72" />
        <Skeleton className="h-12" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (detail.isError) {
    const missing = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="hero-glow py-24">
        <h1 className="font-medium text-6xl tracking-tight">{symbol}</h1>
        <p className="mt-4 max-w-xl text-lg text-ink-secondary">
          {missing
            ? `${symbol} isn't in this quarter's ranking. The model only ranks stocks with enough price and fundamentals history.`
            : "This stock's ranking couldn't be loaded right now."}
        </p>
        <Link to="/" className="mt-8 inline-block text-accent hover:text-accent-strong">
          ← Back to the rankings
        </Link>
      </div>
    );
  }

  const d = detail.data;
  const moved = d.previous ? d.previous.rank - d.rank : null;
  const v = verdict(d.features);
  const net = d.features.reduce((s, f) => s + f.contribution, 0);

  return (
    <div>
      <section className="hero-glow pb-12">
        <p className="pt-10 text-sm text-ink-muted">
          <Link to="/" className="hover:text-ink">
            Rankings
          </Link>{" "}
          / {d.sector ?? "Unclassified"} / {d.ticker}
        </p>
        <div className="mt-3 flex flex-wrap items-end justify-between gap-8">
          <div>
            <h1 className="font-medium text-7xl leading-[0.9] tracking-tight sm:text-[112px]">{d.ticker}</h1>
            <div className="mt-4 flex flex-wrap items-baseline gap-x-5 gap-y-2 text-lg text-ink-secondary">
              <span>
                {d.company_name ?? d.ticker}
                {d.sector ? ` · ${d.sector}` : ""}
              </span>
              <QuoteBadge ticker={d.ticker} />
            </div>
          </div>
          <dl className="flex flex-wrap gap-x-11 gap-y-5">
            <div>
              <dt className="mb-1.5 text-xs uppercase tracking-wider text-ink-muted">Rank</dt>
              <dd className="num text-2xl">
                #{d.rank} of {d.universe_size}
              </dd>
            </div>
            <div>
              <dt className="mb-1.5 text-xs uppercase tracking-wider text-ink-muted">Tier</dt>
              <dd className="text-2xl" style={{ color: TIER_COLORS[d.tier] }}>
                {TIER_NAMES[d.tier]}
              </dd>
            </div>
            <div>
              <dt className="mb-1.5 text-xs uppercase tracking-wider text-ink-muted">In {d.sector ?? "sector"}</dt>
              <dd className="num text-2xl">
                #{d.sector_rank} of {d.sector_size}
              </dd>
            </div>
            <div>
              <dt className="mb-1.5 text-xs uppercase tracking-wider text-ink-muted">Since last quarter</dt>
              <dd className="num text-2xl">
                {moved == null ? (
                  <span className="text-ink-muted">New</span>
                ) : moved === 0 ? (
                  "Unchanged"
                ) : (
                  <span style={{ color: moved > 0 ? "var(--color-accent-strong)" : "#8e97ad" }}>
                    {moved > 0 ? "▲" : "▼"} {Math.abs(moved)} places
                  </span>
                )}
              </dd>
            </div>
          </dl>
        </div>
        {rankings.data && (
          <div className="mt-11">
            <DistributionStrip
              items={rankings.data.items}
              highlight={d.ticker}
              caption={`${d.ticker} ranks above ${d.percentile_above}% of the list`}
            />
          </div>
        )}
      </section>

      <section className="grid gap-12 pb-10 lg:grid-cols-[1.7fr_1fr]">
        <div>
          <h2 className="font-medium text-4xl tracking-tight">How the model got here</h2>
          {d.features.length === 0 ? (
            <p className="mt-4 max-w-xl leading-relaxed text-ink-secondary">
              The input-by-input breakdown is produced when the model retrains. It will appear here
              after the next retrain of the {quarterLabel(d.as_of)} ranking.
            </p>
          ) : (
            <>
              <p className="mt-3 max-w-2xl leading-relaxed text-ink-secondary">
                The score starts from the model's baseline and each of the {d.features.length} inputs
                pushes it up or down. These are the end-of-quarter values the model saw, next to the
                median across all {d.universe_size} ranked stocks.
              </p>
              <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-y border-line py-3.5 text-sm text-ink-secondary">
                <span>
                  Model baseline <b className="num font-medium text-ink">0.0</b>
                </span>
                <span>→ {d.features.length} inputs →</span>
                <span>
                  {d.ticker} <b className="num font-medium text-ink">{formatPoints(net)} points</b> · rank #
                  {d.rank}
                </span>
              </div>
              <Contributions features={d.features} />
              <div className="flex justify-between border-t border-white/20 pt-3.5 text-[15px]">
                <span>Net effect vs the baseline</span>
                <b className="num text-xl font-medium text-accent-strong">{formatPoints(net)}</b>
              </div>
              <p className="mt-4 text-xs leading-relaxed text-ink-muted">
                Points are the model's per-input SHAP contributions ×100; they add up exactly to the
                stock's ranking score. Only the order of scores matters: a higher score ranks higher.
              </p>
            </>
          )}
        </div>

        <div className="space-y-10">
          {v && (
            <div className={PANEL}>
              <h3 className="font-medium text-[28px] leading-tight">{v.title}</h3>
              {v.body && <p className="mt-3 text-sm leading-relaxed text-ink-secondary">{v.body}</p>}
            </div>
          )}
          {overview.data && overview.data.weights.length > 0 && (
            <div className={PANEL}>
              <h3 className="font-medium text-[28px]">What the model weighs most</h3>
              <p className="mb-5 mt-2 text-sm leading-relaxed text-ink-secondary">
                Share of a typical stock's score explained by each input, across this quarter's list.
              </p>
              <WeightBars weights={overview.data.weights} />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
