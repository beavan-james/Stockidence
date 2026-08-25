import { useEffect } from "react";
import { motion, type Variants } from "framer-motion";

import { CommoditiesRow, MacroGrid } from "@/components/discover/MacroCards";
import { EarningsCalendar, IpoCalendar } from "@/components/discover/Calendars";
import { NewsTable } from "@/components/discover/NewsTable";
import { MoverTable } from "@/components/discover/MoverTable";
import { useCommodities, useEarnings, useIpos, useMacro, useMovers } from "@/hooks/queries";

const ease = [0.22, 1, 0.36, 1] as const;

const sectionVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
};

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
        <motion.div
          variants={sectionVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.15 }}
          transition={{ duration: 0.45, ease }}
          className="grid gap-4 lg:grid-cols-3"
        >
          <MoverTable title="Top gainers" rows={movers.data.top_gainers} />
          <MoverTable title="Top losers" rows={movers.data.top_losers} />
          <MoverTable title="Most actively traded" rows={movers.data.most_actively_traded} />
        </motion.div>
      )}

      <motion.section
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, amount: 0.15 }}
        transition={{ duration: 0.45, ease, delay: 0.08 }}
        className="space-y-3"
      >
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-muted">
          Economy &amp; commodities
        </h2>
        {macro.data && macro.data.length > 0 && <MacroGrid metrics={macro.data} />}
        {commodities.data && <CommoditiesRow commodities={commodities.data} />}
      </motion.section>

      <motion.section
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, amount: 0.15 }}
        transition={{ duration: 0.45, ease, delay: 0.16 }}
      >
        <NewsTable />
      </motion.section>

      <motion.section
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, amount: 0.15 }}
        transition={{ duration: 0.45, ease, delay: 0.24 }}
        className="grid gap-4 lg:grid-cols-2"
      >
        {ipos.data && ipos.data.length > 0 && <IpoCalendar listings={ipos.data} />}
        {earnings.data && earnings.data.length > 0 && (
          <EarningsCalendar releases={earnings.data} />
        )}
      </motion.section>
    </div>
  );
}
