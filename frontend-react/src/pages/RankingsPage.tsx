import { useEffect } from "react";
import { Link } from "react-router-dom";

import { LeadFigure, PageHero, Section, Stat } from "@/components/layout/Page";
import { DistributionStrip } from "@/components/ranking/DistributionStrip";
import { ExcessBars, SectorTilt } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { StockLookup } from "@/components/ranking/StockLookup";
import { TierLegend } from "@/components/ranking/TierLabel";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview, useRankings } from "@/hooks/queries";
import { leadingSector } from "@/lib/tiers";
import { QUIET_LINK } from "@/lib/utils";

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
      <PageHero
        eyebrow="Quarterly ranking model"
        link={{ to: "/model", label: "How the model works →" }}
        loading={rankings.isPending}
        title={
          lead && lead.share >= 0.3 ? (
            <>
              This quarter the model leans into <em className="not-italic text-accent">{lead.sector}.</em>
            </>
          ) : (
            <>
              This quarter's favourites are <em className="not-italic text-accent">spread across sectors.</em>
            </>
          )
        }
        lede={
          <>
            Every quarter{n ? `, ${n}` : ""} US stocks are ordered by how likely they are to beat the rest of the list
            over the next three months. Look one up to see where it stands, and why.
          </>
        }
      >
        <div className="mt-10">{n > 0 && <StockLookup items={items} />}</div>

        {rankings.isError ? (
          <p className="mt-10 text-sm text-ink-muted">Rankings are unavailable right now.</p>
        ) : n > 0 ? (
          <div className="mt-10 space-y-3">
            <DistributionStrip items={items} caption={`All ${n} stocks, ranked`} />
            <TierLegend />
          </div>
        ) : null}
      </PageHero>

      <div className="grid gap-x-12 lg:grid-cols-[1.55fr_1fr]">
        <Section
          title="Top of the list"
          aside={
            <a href="#all" className={QUIET_LINK}>
              View all {n} ↓
            </a>
          }
        >
          {rankings.isPending ? <Skeleton className="h-96" /> : <RankingsTable items={items} limit={10} />}
        </Section>

        <div>
          {summary?.avg_excess_vs_spx != null && (
            <Section
              level={3}
              title="Track record"
              aside={
                <Link to="/model" className={QUIET_LINK}>
                  Details →
                </Link>
              }
            >
              <LeadFigure
                value={`${summary.avg_excess_vs_spx >= 0 ? "+" : "−"}${Math.abs(summary.avg_excess_vs_spx * 100).toFixed(1)}`}
                unit="pp"
              />
              <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
                Average quarterly lead of the model's top 20 over the S&amp;P 500 in walk-forward testing.
              </p>
              <div className="mt-5">
                <ExcessBars quarters={overview.data!.track_record} />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-5 border-t border-line pt-5">
                <Stat value={`${Math.round((summary.hit_rate_vs_spx ?? 0) * 100)}%`} label="of quarters beat the index" />
                <Stat value={summary.quarters} label="quarters tested" />
              </div>
            </Section>
          )}
          {n > 0 && (
            <Section level={3} title="Where the top fifth sits">
              <SectorTilt items={items} />
            </Section>
          )}
        </div>
      </div>

      <Section id="all" title={`All ${n} rankings`}>
        {n > 0 && <RankingsTable items={items} />}
      </Section>
    </div>
  );
}
