import { useEffect, useState } from "react";
import { motion } from "framer-motion";

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
      className="space-y-8 py-10 text-center"
    >
      <div className="space-y-1">
        <h2 className="title-glow text-lg font-semibold tracking-tight">
          {headline(source, ticker)}
        </h2>
        <p className="text-xs text-ink-muted">{subtitle(source)}</p>
      </div>

      <div
        className="mx-auto h-1 max-w-sm overflow-hidden rounded-full bg-raised"
        role="progressbar"
        aria-label="Loading"
      >
        <motion.div
          className="h-full w-1/3 rounded-full bg-accent"
          style={{ boxShadow: "0 0 24px var(--color-accent), 0 0 64px var(--color-accent)" }}
          animate={{ x: ["-100%", "300%"] }}
          transition={{ duration: 1.4, ease: "easeInOut", repeat: Infinity }}
        />
      </div>

      <ol className="mx-auto flex max-w-lg flex-wrap items-center justify-center gap-y-2 text-xs">
        {STAGES.map((label, i) => (
          <li key={label} className="flex items-center">
            <motion.span
              key={`${label}-${i === stage ? "on" : "off"}`}
              initial={false}
              animate={
                i === stage
                  ? { scale: [1, 1.08, 1], opacity: 1 }
                  : { scale: 1, opacity: i < stage ? 1 : 0.55 }
              }
              transition={{ duration: 0.6, repeat: i === stage ? Infinity : 0 }}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1 transition-colors duration-500",
                i === stage
                  ? "border-accent/60 bg-accent-dim text-accent-strong"
                  : i < stage
                    ? "border-line bg-raised text-ink-secondary"
                    : "border-line/60 text-ink-muted/60",
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  i === stage
                    ? "bg-accent"
                    : i < stage
                      ? "bg-accent/50"
                      : "bg-line",
                )}
                style={
                  i === stage
                    ? { boxShadow: "0 0 8px var(--color-accent)" }
                    : undefined
                }
              />
              {label}
            </motion.span>
            {i < STAGES.length - 1 && (
              <span
                className={cn(
                  "mx-1 transition-colors duration-500",
                  i < stage ? "text-accent/60" : "text-ink-muted/50",
                )}
              >
                ›
              </span>
            )}
          </li>
        ))}
      </ol>

      <motion.p
        key={tenet}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="text-sm italic text-ink-secondary"
      >
        {TENETS[tenet]}
      </motion.p>

      <p className="text-xs text-ink-muted">
        Still working — fundamentals are the slow part. This page updates itself the moment
        the numbers land.
      </p>
    </motion.div>
  );
}
