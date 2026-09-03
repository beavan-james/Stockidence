import { useEffect, useMemo } from "react";
import { motion, type Variants } from "framer-motion";

import { CommoditiesRow, MacroGrid } from "@/components/discover/MacroCards";
import { EarningsCalendar, IpoCalendar } from "@/components/discover/Calendars";
import { NewsTable } from "@/components/discover/NewsTable";
import { MoverTable } from "@/components/discover/MoverTable";
import { RankingTable } from "@/components/discover/RankingTable";
import {
    useCommodities,
    useEarnings,
    useIpos,
    useMacro,
    useMovers,
} from "@/hooks/queries";
import type { Mover } from "@/types/api";

const ease = [0.22, 1, 0.36, 1] as const;

const sectionVariants: Variants = {
    hidden: { opacity: 0, y: 14 },
    visible: { opacity: 1, y: 0 },
};

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
        document.title = "Discover — Stockidence";
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
        <div className="space-y-8">
            <div className="flex items-baseline justify-between">
                <h1 className="text-xl font-semibold tracking-tight">
                    Discover
                </h1>
            {movers.data?.movers_as_of && (
                <span className="text-xs text-ink-muted">
                    Market close · {movers.data.movers_as_of}
                </span>
            )}
            </div>

            <motion.section
                variants={sectionVariants}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.15 }}
                transition={{ duration: 0.7, ease }}
            >
                <RankingTable />
            </motion.section>

            {movers.data && (
                <motion.div
                    variants={sectionVariants}
                    initial="hidden"
                    whileInView="visible"
                    viewport={{ once: true, amount: 0.15 }}
                    transition={{ duration: 0.7, ease }}
                    className="grid gap-4 lg:grid-cols-3"
                >
                    <MoverTable title="Top gainers" rows={sortedGainers} />
                    <MoverTable title="Top losers" rows={sortedLosers} />
                    <MoverTable
                        title="Most actively traded"
                        rows={sortedActive}
                    />
                </motion.div>
            )}

            <motion.section
                variants={sectionVariants}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.15 }}
                transition={{ duration: 0.7, ease, delay: 0.08 }}
                className="space-y-3"
            >
                <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-muted">
                    Economy &amp; commodities
                </h2>
                {macro.data && macro.data.length > 0 && (
                    <MacroGrid metrics={macro.data} />
                )}
                {commodities.data && (
                    <CommoditiesRow commodities={commodities.data} />
                )}
            </motion.section>

            <motion.section
                variants={sectionVariants}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.15 }}
                transition={{ duration: 0.7, ease, delay: 0.16 }}
            >
                <NewsTable />
            </motion.section>

            <motion.section
                variants={sectionVariants}
                initial="hidden"
                whileInView="visible"
                viewport={{ once: true, amount: 0.15 }}
                transition={{ duration: 0.7, ease, delay: 0.24 }}
                className="grid gap-4 lg:grid-cols-2"
            >
                {ipos.data && ipos.data.length > 0 && (
                    <IpoCalendar listings={ipos.data} />
                )}
                {earnings.data && earnings.data.length > 0 && (
                    <EarningsCalendar releases={earnings.data} />
                )}
            </motion.section>
        </div>
    );
}
