import { useEffect } from "react";

import { MacroGrid } from "@/components/discover/MacroCards";
import { EarningsCalendar, IpoCalendar } from "@/components/discover/Calendars";
import { MoverTable } from "@/components/discover/MoverTable";
import { PageHero, Section } from "@/components/layout/Page";
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
        <div>
            <PageHero
                title="Market Info"
            />

            {movers.data || movers.isError ? (
                <Section
                    title="Daily movers"
                    aside={
                        movers.data?.movers_as_of && (
                            <p className="text-sm text-ink-muted">As of the {movers.data.movers_as_of} close</p>
                        )
                    }
                >
                    {!movers.data ? (
                        <p className="text-sm text-ink-muted">
                            Market movers unavailable right now.
                        </p>
                    ) : (
                        <div className="grid gap-x-10 gap-y-10 lg:grid-cols-3">
                            <MoverTable title="Top gainers" rows={gainers} />
                            <MoverTable title="Top losers" rows={losers} />
                            <MoverTable
                                title="Most actively traded"
                                rows={active}
                            />
                        </div>
                    )}
                </Section>
            ) : null}

            <Section title="Economy &amp; commodities">
                <MacroGrid metrics={macro.data ?? []} commodities={commodities.data ?? []} />
            </Section>

            <Section title="Calendars">
                <div className="grid gap-x-10 gap-y-10 lg:grid-cols-2">
                    {ipos.data && ipos.data.length > 0 && (
                        <IpoCalendar listings={ipos.data} />
                    )}
                    {earnings.data && earnings.data.length > 0 && (
                        <EarningsCalendar releases={earnings.data} />
                    )}
                </div>
            </Section>
        </div>
    );
}
