import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { PageHero, Section, Stat } from "@/components/layout/Page";
import { QuoteBadge } from "@/components/profile/QuoteBadge";
import { DistributionStrip } from "@/components/ranking/DistributionStrip";
import { WeightBars } from "@/components/ranking/ModelCharts";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview, useRankingDetail, useRankings, useWeekly } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { featureMeta, formatFeature, formatPoints } from "@/lib/features";
import { TIER_COLORS, TIER_NAMES, quarterLabel } from "@/lib/tiers";
import { cn, leadTone } from "@/lib/utils";
import type { FeatureContribution } from "@/types/api";

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
    <div className="-mt-px md:mt-6">
      <div className="hidden grid-cols-[minmax(0,1.35fr)_6.5rem_6.5rem_minmax(0,1.2fr)_3.5rem] gap-4 pb-2 text-xs uppercase tracking-wider text-ink-muted md:grid">
        <span>Input</span>
        <span>This stock</span>
        <span>List median</span>
        <span className="text-center">Down · up</span>
        <span className="text-right">Pts</span>
      </div>
      {features.map((f) => {
        const meta = featureMeta(f.feature);
        const w = (Math.abs(f.contribution) / max) * 50;
        const up = f.contribution >= 0;
        return (
          <div
            key={f.feature}
            className="bar-target grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-t border-line py-3 md:grid-cols-[minmax(0,1.35fr)_6.5rem_6.5rem_minmax(0,1.2fr)_3.5rem]"
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
                className={`bar absolute inset-y-0 ${up ? "" : "bar-down"}`}
                style={{ left: up ? "50%" : `${50 - w}%`, width: `${w}%` }}
              />
            </div>
            <div
              className={`num col-start-2 row-start-1 text-right text-[15px] font-medium md:col-start-auto md:row-start-auto ${leadTone(up)}`}
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
  const weekly = useWeekly();

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
      <PageHero
        eyebrow="Quarterly ranking model"
        link={{ to: "/", label: "← This quarter's list" }}
        title={symbol}
        lede={
          missing
            ? `${symbol} isn't in this quarter's ranking. The quarterly model only ranks stocks with enough price and fundamentals history.`
            : "This stock's ranking couldn't be loaded right now."
        }
      />
    );
  }

  const d = detail.data;
  const moved = d.previous ? d.previous.rank - d.rank : null;
  const v = verdict(d.features);
  const net = d.features.reduce((s, f) => s + f.contribution, 0);
  const weeklyRank = weekly.data?.items.find((r) => r.ticker === d.ticker)?.rank;
  const weights = overview.data?.weights ?? [];

  return (
    <div>
      <PageHero
        eyebrow={`Quarterly ranking model · ${quarterLabel(d.as_of)}`}
        link={
          weeklyRank != null
            ? { to: "/week", label: `On this week's list: #${weeklyRank} of ${weekly.data?.universe_size} →` }
            : null
        }
        title={d.ticker}
      >
        <div className="mt-6 flex flex-wrap items-baseline gap-x-5 gap-y-2 text-lg text-ink-secondary">
          <span>
            {d.company_name ?? d.ticker}
            {d.sector ? ` · ${d.sector}` : ""}
          </span>
          <QuoteBadge ticker={d.ticker} />
        </div>
        <div className="mt-10 flex flex-wrap gap-x-11 gap-y-5">
          <Stat value={`#${d.rank} of ${d.universe_size}`} label="quarterly rank" />
          <Stat value={<span style={{ color: TIER_COLORS[d.tier] }}>{TIER_NAMES[d.tier]}</span>} label="tier" />
          <Stat value={`#${d.sector_rank} of ${d.sector_size}`} label={`in ${d.sector ?? "its sector"}`} />
          <Stat
            value={
              moved == null ? (
                <span className="text-ink-muted">New</span>
              ) : moved === 0 ? (
                "Unchanged"
              ) : (
                <span className={leadTone(moved > 0)}>
                  {moved > 0 ? "▲" : "▼"} {Math.abs(moved)} places
                </span>
              )
            }
            label="since last quarter"
          />
        </div>
        {rankings.data && (
          <div className="mt-10">
            <DistributionStrip
              items={rankings.data.items}
              highlight={d.ticker}
              caption={`${d.ticker} ranks above ${d.percentile_above}% of this quarter's list`}
            />
          </div>
        )}
      </PageHero>

      <div className={cn((v || weights.length > 0) && "grid gap-x-12 lg:grid-cols-[1.7fr_1fr]")}>
        <Section title="How the quarterly model got here">
          {d.features.length === 0 ? (
            <p className="max-w-xl leading-relaxed text-ink-secondary">
              The input-by-input breakdown is produced when the model retrains. It will appear here
              after the next retrain of the {quarterLabel(d.as_of)} ranking.
            </p>
          ) : (
            <>
              <p className="max-w-2xl leading-relaxed text-ink-secondary">
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
        </Section>

        <div>
          {v && <Section level={3} title={v.title} intro={v.body || undefined} />}
          {weights.length > 0 && (
            <Section
              level={3}
              title="What the quarterly model weighs most"
              intro="Share of a typical stock's score explained by each input, across this quarter's list."
            >
              <WeightBars weights={weights} />
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
