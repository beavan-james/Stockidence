import { useEffect } from "react";

import { CommoditiesRow, MacroGrid } from "@/components/discover/MacroCards";
import { EarningsCalendar, IpoCalendar } from "@/components/discover/Calendars";
import { NewsTable } from "@/components/discover/NewsTable";
import { MoverTable } from "@/components/discover/MoverTable";
import {
    useCommodities,
    useEarnings,
    useIpos,
    useMacro,
    useMovers,
} from "@/hooks/queries";

export function MarketPage() {
    const movers = useMovers();
    const macro = useMacro();
    const commodities = useCommodities();
    const ipos = useIpos();
    const earnings = useEarnings();

    useEffect(() => {
        document.title = "Market | Stockidence";
    }, []);

    // The API returns each list already ranked and capped (latest snapshot
    // only): gainers/losers by dollar change x volume, most active by dollar
    // volume. Render them as-is.
    const gainers = movers.data?.top_gainers ?? [];
    const losers = movers.data?.top_losers ?? [];
    const active = movers.data?.most_actively_traded ?? [];

    return (
        <div className="space-y-14 pb-10">
            <section className="hero-glow pb-2">
                <p className="pt-10 text-xs uppercase tracking-[0.14em] text-ink-secondary">
                    Market
                </p>
                <h1 className="mt-4 font-display text-5xl tracking-tight sm:text-6xl">
                    Around the market
                </h1>
                <p className="mt-4 max-w-2xl text-lg leading-relaxed text-ink-secondary">
                    Context for the rankings: the day's movers, the economy, news and what's coming up.
                    {movers.data?.movers_as_of && (
                        <span className="text-ink-muted"> Movers as of the {movers.data.movers_as_of} close.</span>
                    )}
                </p>
            </section>

            {movers.data || movers.isError ? (
                <section className="space-y-5">
                    <h2 className="font-display text-3xl tracking-tight">
                        Daily movers
                    </h2>
                    {!movers.data ? (
                        <p className="text-sm text-ink-muted">
                            Market movers unavailable right now.
                        </p>
                    ) : (
                    <div className="grid gap-4 lg:grid-cols-3">
                        <MoverTable title="Top gainers" rows={gainers} />
                        <MoverTable title="Top losers" rows={losers} />
                        <MoverTable
                            title="Most actively traded"
                            rows={active}
                        />
                    </div>
                    )}
                </section>
            ) : null}

            <section className="space-y-5">
                <h2 className="font-display text-3xl tracking-tight">
                    Economy &amp; commodities
                </h2>
                {macro.data && macro.data.length > 0 && (
                    <MacroGrid metrics={macro.data} />
                )}
                {commodities.data && (
                    <CommoditiesRow commodities={commodities.data} />
                )}
            </section>

            <section className="space-y-5">
                <h2 className="font-display text-3xl tracking-tight">
                    News
                </h2>
                <NewsTable />
            </section>

            <section className="space-y-5">
                <h2 className="font-display text-3xl tracking-tight">
                    Calendars
                </h2>
                <div className="grid gap-4 lg:grid-cols-2">
                    {ipos.data && ipos.data.length > 0 && (
                        <IpoCalendar listings={ipos.data} />
                    )}
                    {earnings.data && earnings.data.length > 0 && (
                        <EarningsCalendar releases={earnings.data} />
                    )}
                </div>
            </section>
        </div>
    );
}
