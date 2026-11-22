import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { LeadFigure, Section, Stat, TITLE } from "@/components/layout/Page";
import { DistributionStrip } from "@/components/ranking/DistributionStrip";
import { ExcessBars } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { SplatHero } from "@/components/ranking/SplatHero";
import { StockLookup } from "@/components/ranking/StockLookup";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelOverview, useRankings } from "@/hooks/queries";
import { leadingSector } from "@/lib/tiers";
import { QUIET_LINK, cn } from "@/lib/utils";

export function RankingsPage() {
  const rankings = useRankings();
  const overview = useModelOverview();
  const [match, setMatch] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Stockidence | Quarterly stock ranking";
  }, []);

  const items = rankings.data?.items ?? [];
  const n = items.length;
  const lead = leadingSector(items);
  const summary = overview.data?.summary;

  return (
    <div>
      <SplatHero
        items={items}
        pinned={match}
        fallback={n > 0 && <DistributionStrip items={items} />}
      >
        <Link to="/model" className={cn(QUIET_LINK, "mb-5 inline-block")}>
          How the model works →
        </Link>
        {rankings.isPending ? (
          <Skeleton className="h-40 max-w-xl" />
        ) : (
          <h1 className={cn(TITLE, "max-w-[620px]")}>
            {lead && lead.share >= 0.3 ? (
              <>
                This quarter the model leans into <span className="text-accent">{lead.sector}.</span>
              </>
            ) : (
              <>
                This quarter's favourites are <span className="text-accent">spread across sectors.</span>
              </>
            )}
          </h1>
        )}
        <p className="mt-6 max-w-[540px] text-lg leading-relaxed text-ink-secondary">
          Every quarter{n ? `, ${n}` : ""} US stocks are ordered by how likely they are to beat the rest of the list
          over the next three months.
        </p>
        {rankings.isError ? (
          <p className="mt-10 text-sm text-ink-muted">Rankings are unavailable right now.</p>
        ) : (
          n > 0 && (
            <div className="mt-10">
              <StockLookup items={items} onMatch={setMatch} />
            </div>
          )
        )}
      </SplatHero>

      <div className="pt-12 sm:pt-[72px]">
        {summary?.avg_excess_vs_spx != null && (
          <Section
            title="Track record"
            aside={
              <Link to="/model" className={QUIET_LINK}>
                Details →
              </Link>
            }
          >
            <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
              <div>
                <LeadFigure
                  value={`${summary.avg_excess_vs_spx >= 0 ? "+" : "−"}${Math.abs(summary.avg_excess_vs_spx * 100).toFixed(1)}`}
                  unit="pp"
                />
                <p className="mt-3 text-sm leading-relaxed text-ink-secondary">
                  Average quarterly lead of the model's top 20 over the S&amp;P 500 in walk-forward testing.
                </p>
                <div className="mt-6 grid grid-cols-2 gap-5 border-t border-line pt-5">
                  <Stat
                    value={`${Math.round((summary.hit_rate_vs_spx ?? 0) * 100)}%`}
                    label="of quarters beat the index"
                  />
                  <Stat value={summary.quarters} label="quarters tested" />
                </div>
              </div>
              <ExcessBars quarters={overview.data!.track_record} height={110} />
            </div>
          </Section>
        )}

        <Section title="Full rankings">
          {rankings.isPending ? <Skeleton className="h-[520px]" /> : n > 0 && <RankingsTable items={items} />}
        </Section>
      </div>
    </div>
  );
}
