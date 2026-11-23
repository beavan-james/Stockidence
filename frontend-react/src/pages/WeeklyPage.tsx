import { useEffect } from "react";
import { Link } from "react-router-dom";

import { LeadFigure, PageHero, Section, Stat } from "@/components/layout/Page";
import { WeeklyExcessBars } from "@/components/ranking/ModelCharts";
import { RankingsTable } from "@/components/ranking/RankingsTable";
import { useWeekly } from "@/hooks/queries";
import { dayLabel } from "@/lib/tiers";
import { QUIET_LINK } from "@/lib/utils";
import type { WeeklyEnvelope } from "@/types/api";

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
        link={{ to: "/week/method", label: "How the model works →" }}
        title="Weekly Stock Rankings"
        lede={
          d?.week_of
            ? `Week of ${dayLabel(d.week_of)}.`
            : d && "The first list lands Friday after the close."
        }
      >
        {weekly.isError && <p className="mt-10 text-sm text-ink-muted">This week's list is unavailable right now.</p>}
      </PageHero>

      {d?.backtest && <TrackRecord backtest={d.backtest} />}

      {n > 0 && (
        <Section title="Full rankings">
          <RankingsTable items={items} showChange={d?.previous != null} />
        </Section>
      )}
    </div>
  );
}

function TrackRecord({ backtest }: { backtest: NonNullable<WeeklyEnvelope["backtest"]> }) {
  const recent = backtest.track.slice(-52);
  return (
    <Section
      title="Track record"
      aside={
        <Link to="/week/method" className={QUIET_LINK}>
          Details →
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
        </div>
      </div>
    </Section>
  );
}
