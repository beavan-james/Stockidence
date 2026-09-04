import { useEffect } from "react";
import { motion, type Variants } from "framer-motion";

import { RankingTable } from "@/components/discover/RankingTable";

const ease = [0.22, 1, 0.36, 1] as const;

const sectionVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: { opacity: 1, y: 0 },
};

const HIGHLIGHTS = [
  {
    label: "What it is",
    text: "An XGBoost ranking model. It does not predict prices — it orders stocks so the top of the list beats the bottom.",
  },
  {
    label: "Trained on",
    text: "Quarterly bars and fundamentals going back to 2011, spanning a 520-stock universe.",
  },
  {
    label: "What it does",
    text: "Ranks stocks by expected return over the next quarter. The score is a pure ordering signal, not a forecast of any price increase.",
  },
  {
    label: "How it's trained",
    text: "Walk-forward validated quarter by quarter, optimized with the rank:ndcg objective for the head of the list.",
  },
] as const;

export function ModelPage() {
  useEffect(() => {
    document.title = "Model — Stockidence";
  }, []);

  return (
    <div className="space-y-10">
      <div className="flex items-baseline justify-between">
        <h1 className="title-glow text-xl font-semibold tracking-tight">Model</h1>
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

      <motion.section
        variants={sectionVariants}
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, amount: 0.2 }}
        transition={{ duration: 0.7, ease, delay: 0.08 }}
      >
        <dl>
          {HIGHLIGHTS.map((h) => (
            <div
              key={h.label}
              className="grid gap-1 border-t border-line/60 py-4 sm:grid-cols-[12rem_1fr] sm:gap-6"
            >
              <dt className="text-sm font-medium text-ink">{h.label}</dt>
              <dd className="text-sm leading-relaxed text-ink-secondary">{h.text}</dd>
            </div>
          ))}
        </dl>
      </motion.section>
    </div>
  );
}
