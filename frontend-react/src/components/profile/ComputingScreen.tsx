import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const STAGES = [
  "Queued",
  "Fetching market data",
  "Cleaning & staging",
  "Deriving indicators",
  "Scoring",
];

const TENETS = [
  "Fair value anchors the verdict.",
  "Every statistic traces back to a source.",
  "Same inputs, same numbers. Every time.",
];

function headline(source: string, ticker?: string): string {
  if (source === "pending") return ticker ? `Loading ${ticker}` : "Loading ticker";
  if (source === "refreshing") return ticker ? `Refreshing ${ticker}` : "Refreshing";
  return ticker ? `Computing ${ticker}` : "Computing";
}

function subtitle(source: string): string {
  if (source === "pending")
    return "Assembling its full history from scratch — this is the slow path.";
  if (source === "refreshing")
    return "The stored snapshot is over a day old — updating market inputs.";
  return "The pipeline was queued.";
}

/** Pipeline-in-progress screen shown while source is pending/refreshing. */
export function ComputingScreen({ source, ticker }: { source: string; ticker?: string }) {
  const [stage, setStage] = useState(0);
  const [tenet, setTenet] = useState(0);

  useEffect(() => {
    const stageTimer = setInterval(() => setStage((s) => (s + 1) % STAGES.length), 1800);
    const tenetTimer = setInterval(() => setTenet((t) => (t + 1) % TENETS.length), 4000);
    return () => {
      clearInterval(stageTimer);
      clearInterval(tenetTimer);
    };
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      <Card>
        <CardContent className="space-y-6 p-10 text-center">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold tracking-tight">{headline(source, ticker)}</h2>
            <p className="text-xs text-ink-muted">{subtitle(source)}</p>
          </div>

          <div
            className="mx-auto h-1 max-w-sm overflow-hidden rounded-full bg-raised"
            role="progressbar"
            aria-label="Loading"
          >
            <motion.div
              className="h-full w-1/3 rounded-full bg-accent"
              style={{ boxShadow: "0 0 16px var(--color-accent)" }}
              animate={{ x: ["-100%", "300%"] }}
              transition={{ duration: 1.6, ease: "easeInOut", repeat: Infinity }}
            />
          </div>

          <div className="flex flex-wrap items-center justify-center gap-1 text-xs">
            {STAGES.map((label, i) => (
              <span key={label} className="flex items-center gap-1">
                <span
                  className={cn(
                    "rounded-full border px-3 py-1 transition-colors duration-700",
                    i === stage
                      ? "border-accent/50 bg-accent-dim text-accent-strong"
                      : i < stage
                        ? "border-line bg-raised text-ink-secondary"
                        : "border-line/60 text-ink-muted/60",
                  )}
                >
                  {label}
                </span>
                {i < STAGES.length - 1 && <span className="text-ink-muted/50">›</span>}
              </span>
            ))}
          </div>

          <motion.p
            key={tenet}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="text-sm italic text-ink-secondary"
          >
            {TENETS[tenet]}
          </motion.p>

          <p className="text-xs text-ink-muted">
            Still working — fundamentals are the slow part. This page updates itself the moment
            the numbers land.
          </p>
        </CardContent>
      </Card>
    </motion.div>
  );
}
