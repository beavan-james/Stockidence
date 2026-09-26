import { useEffect, useMemo } from "react";

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
import type { Mover } from "@/types/api";

function parseVolume(m: Mover): number {
    return parseInt(m.volume, 10) || 0;
}

function parseChangePct(m: Mover): number {
    return parseFloat(m.change_percentage) || 0;
}

function processMovers(gainers: Mover[], losers: Mover[], active: Mover[]) {
    const volumeThreshold = 1_000_000;

    const sortedGainers = [...gainers]
        .filter((m) => parseVolume(m) > volumeThreshold)
        .sort((a, b) => parseChangePct(b) - parseChangePct(a));

    const sortedLosers = [...losers]
        .filter((m) => parseVolume(m) > volumeThreshold)
        .sort((a, b) => parseChangePct(a) - parseChangePct(b));

    const sortedActive = [...active].sort(
        (a, b) => parseVolume(b) - parseVolume(a)
    );

    return { sortedGainers, sortedLosers, sortedActive };
}

export function DiscoverPage() {
    const movers = useMovers();
    const macro = useMacro();
    const commodities = useCommodities();
    const ipos = useIpos();
    const earnings = useEarnings();

    useEffect(() => {
        document.title = "Discover | Stockidence";
    }, []);

    const { sortedGainers, sortedLosers, sortedActive } = useMemo(
        () =>
            movers.data
                ? processMovers(
                      movers.data.top_gainers,
                      movers.data.top_losers,
                      movers.data.most_actively_traded
                  )
                : { sortedGainers: [], sortedLosers: [], sortedActive: [] },
        [movers.data]
    );

    return (
        <div className="space-y-12">
            <div className="flex items-baseline justify-between">
                <h1 className="title-glow text-xl font-semibold tracking-tight">
                    Discover
                </h1>
                {movers.data?.movers_as_of && (
                    <span className="text-xs text-ink-muted">
                        Market close · {movers.data.movers_as_of}
                    </span>
                )}
            </div>

            {movers.data || movers.isError ? (
                <section className="anim-rise space-y-4 pt-4">
                    <h2 className="title-glow w-fit text-lg font-semibold tracking-tight">
                        Daily Movement
                    </h2>
                    {!movers.data ? (
                        <p className="text-sm text-ink-muted">
                            Market movers unavailable right now.
                        </p>
                    ) : (
                    <div className="grid gap-4 lg:grid-cols-3">
                        <MoverTable title="Top gainers" rows={sortedGainers} />
                        <MoverTable title="Top losers" rows={sortedLosers} />
                        <MoverTable
                            title="Most actively traded"
                            rows={sortedActive}
                        />
                    </div>
                    )}
                </section>
            ) : null}

            <section className="anim-rise space-y-4 pt-4">
                <h2 className="title-glow w-fit text-lg font-semibold tracking-tight">
                    Economy &amp; commodities
                </h2>
                {macro.data && macro.data.length > 0 && (
                    <MacroGrid metrics={macro.data} />
                )}
                {commodities.data && (
                    <CommoditiesRow commodities={commodities.data} />
                )}
            </section>

            <section className="anim-rise space-y-4 pt-4">
                <h2 className="title-glow w-fit text-lg font-semibold tracking-tight">
                    News &amp; sentiment
                </h2>
                <NewsTable />
            </section>

            <section className="anim-rise space-y-4 pt-4">
                <h2 className="title-glow w-fit text-lg font-semibold tracking-tight">
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
