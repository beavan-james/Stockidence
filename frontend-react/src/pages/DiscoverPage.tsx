import { useEffect } from "react";

import { CommoditiesRow, MacroGrid } from "@/components/discover/MacroCards";
import { EarningsCalendar, IpoCalendar } from "@/components/discover/Calendars";
import { NewsTable } from "@/components/discover/NewsTable";
import { MoverTable } from "@/components/discover/MoverTable";
import { useCommodities, useEarnings, useIpos, useMacro, useMovers } from "@/hooks/queries";

export function DiscoverPage() {
  const movers = useMovers();
  const macro = useMacro();
  const commodities = useCommodities();
  const ipos = useIpos();
  const earnings = useEarnings();

  useEffect(() => {
    document.title = "Discover — Stockidence";
  }, []);

  return (
    <div className="space-y-8">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Discover</h1>
        {movers.data?.movers_as_of && (
          <span className="text-xs text-ink-muted">
            Market close · {movers.data.movers_as_of}
          </span>
        )}
      </div>

      {movers.data && (
        <div className="anim-rise grid gap-4 lg:grid-cols-3">
          <MoverTable title="Top gainers" rows={movers.data.top_gainers} />
          <MoverTable title="Top losers" rows={movers.data.top_losers} />
          <MoverTable title="Most actively traded" rows={movers.data.most_actively_traded} />
        </div>
      )}

      <section className="anim-rise space-y-3" style={{ animationDelay: "100ms" }}>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-muted">
          Economy &amp; commodities
        </h2>
        {macro.data && macro.data.length > 0 && <MacroGrid metrics={macro.data} />}
        {commodities.data && <CommoditiesRow commodities={commodities.data} />}
      </section>

      <section className="anim-rise" style={{ animationDelay: "200ms" }}>
        <NewsTable />
      </section>

      <section
        className="anim-rise grid gap-4 lg:grid-cols-2"
        style={{ animationDelay: "300ms" }}
      >
        {ipos.data && ipos.data.length > 0 && <IpoCalendar listings={ipos.data} />}
        {earnings.data && earnings.data.length > 0 && (
          <EarningsCalendar releases={earnings.data} />
        )}
      </section>
    </div>
  );
}
