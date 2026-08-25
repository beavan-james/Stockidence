import { useEffect, useState } from "react";

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
  "Valuation leads the verdict.",
  "Volatility informs — it never decides.",
  "Every sub-score traces back to a source.",
  "Same inputs, same rating. Every time.",
];

function headline(source: string, ticker?: string): string {
  if (source === "pending") return ticker ? `First rating for ${ticker}` : "Computing your first rating";
  if (source === "refreshing") return ticker ? `Refreshing ${ticker}` : "Refreshing";
  return ticker ? `Computing a rating for ${ticker}` : "Computing a rating";
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
    <Card>
      <CardContent className="space-y-6 p-10 text-center">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">{headline(source, ticker)}</h2>
          <p className="text-xs text-ink-muted">{subtitle(source)}</p>
        </div>

        <svg viewBox="0 0 120 120" className="mx-auto h-28 w-28" role="img" aria-label="Computing">
          <circle cx="60" cy="60" r="48" fill="none" stroke="#26262b" strokeWidth="6" />
          <circle
            cx="60"
            cy="60"
            r="48"
            fill="none"
            stroke="#818cf8"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray="90 212"
            className="cg-gauge-sweep origin-center"
          />
          <text x="60" y="57" textAnchor="middle" style={{ fontSize: 9 }} className="fill-zinc-500">
            CALIBRATING
          </text>
        </svg>

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

        <p key={tenet} className="cg-fade text-sm italic text-ink-secondary">
          {TENETS[tenet]}
        </p>

        <p className="cg-reassure text-xs text-ink-muted">
          Still working — fundamentals are the slow part. This page updates itself the moment
          the rating lands.
        </p>
      </CardContent>
    </Card>
  );
}
