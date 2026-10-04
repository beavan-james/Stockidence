import { useEffect } from "react";
import { Link } from "react-router-dom";

import { DistributionStrip } from "@/components/ranking/DistributionStrip";
import { ExcessBars, SectorTilt } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { StockLookup } from "@/components/ranking/StockLookup";
import { TierLegend } from "@/components/ranking/TierPill";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview, useRankings } from "@/hooks/queries";
import { leadingSector } from "@/lib/tiers";

export function RankingsPage() {
  const rankings = useRankings();
  const overview = useModelOverview();

  useEffect(() => {
    document.title = "Stockidence | Quarterly stock ranking";
  }, []);

  const items = rankings.data?.items ?? [];
  const n = items.length;
  const lead = leadingSector(items);
  const summary = overview.data?.summary;

  return (
    <div>
      <section className="hero-glow pb-14">
        <p className="pt-10 text-xs uppercase tracking-[0.14em] text-ink-secondary">
          Quarterly ranking model
        </p>
        {rankings.isPending ? (
          <Skeleton className="mt-5 h-40 max-w-3xl" />
        ) : (
          <h1 className="mt-4 max-w-4xl font-medium text-5xl leading-[1.02] tracking-tight sm:text-7xl lg:text-[84px]">
            {lead && lead.share >= 0.3 ? (
              <>
                This quarter the model leans into <em className="not-italic text-accent">{lead.sector}.</em>
              </>
            ) : (
              <>
                This quarter's favourites are <em className="not-italic text-accent">spread across sectors.</em>
              </>
            )}
          </h1>
        )}
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-secondary">
          Every quarter{n ? `, ${n}` : ""} US stocks are ordered by how likely they are to beat the
          rest of the list over the next three months. Look one up to see where it stands, and why.
        </p>

        <div className="mt-10">{n > 0 && <StockLookup items={items} />}</div>

        {rankings.isError ? (
          <p className="mt-10 text-sm text-ink-muted">Rankings are unavailable right now.</p>
        ) : n > 0 ? (
          <div className="mt-10 space-y-3">
            <DistributionStrip items={items} caption={`All ${n} stocks, ranked`} />
            <TierLegend />
          </div>
        ) : null}
      </section>

      <section className="grid gap-12 pb-16 lg:grid-cols-[1.55fr_1fr]">
        <div>
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="font-medium text-4xl tracking-tight">Top of the list</h2>
            <a href="#all" className="text-sm text-ink-secondary hover:text-ink">
              View all {n} ↓
            </a>
          </div>
          {rankings.isPending ? (
            <Skeleton className="h-96" />
          ) : (
            <RankingsTable items={items} limit={10} />
          )}
        </div>

        <div className="space-y-10">
          {summary?.avg_excess_vs_spx != null && (
            <div className="border-t border-line pt-6">
              <div className="flex items-baseline justify-between">
                <h3 className="font-medium text-2xl">Track record</h3>
                <Link to="/model" className="text-sm text-ink-secondary hover:text-ink">
                  Details →
                </Link>
              </div>
              <p className="num mt-4 font-medium text-6xl leading-none tracking-tight">
                {summary.avg_excess_vs_spx >= 0 ? "+" : "−"}
                {Math.abs(summary.avg_excess_vs_spx * 100).toFixed(1)}
                <span className="text-3xl"> pp</span>
              </p>
              <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
                Average quarterly lead of the model's top 20 over the S&amp;P 500 in walk-forward
                testing.
              </p>
              <div className="mt-5">
                <ExcessBars quarters={overview.data!.track_record} />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-5 border-t border-line pt-5">
                <div>
                  <p className="num text-2xl">{Math.round((summary.hit_rate_vs_spx ?? 0) * 100)}%</p>
                  <p className="text-xs text-ink-muted">of quarters beat the index</p>
                </div>
                <div>
                  <p className="num text-2xl">{summary.quarters}</p>
                  <p className="text-xs text-ink-muted">quarters tested</p>
                </div>
              </div>
            </div>
          )}
          {n > 0 && (
            <div className="border-t border-line pt-6">
              <h3 className="mb-4 font-medium text-2xl">Where the top fifth sits</h3>
              <SectorTilt items={items} />
            </div>
          )}
        </div>
      </section>

      <section id="all" className="scroll-mt-24 pb-10">
        <h2 className="mb-4 font-medium text-4xl tracking-tight">All {n} rankings</h2>
        {n > 0 && <RankingsTable items={items} />}
      </section>
    </div>
  );
}
