import { AnimatedNumber } from "@/components/ui/AnimatedNumber";
import { Scale } from "lucide-react";

/** Fair value + 12m target when the model has a valuation anchor. */
export function ValuationReference({
  fairValue,
  targetPrice,
}: {
  fairValue: number | null;
  targetPrice: number | null;
}) {
  if (fairValue == null && targetPrice == null) return null;

  return (
    <div className="anim-rise space-y-4" style={{ animationDelay: "80ms" }}>
      <div className="flex items-center gap-2 text-accent">
        <Scale size={18} />
        <h3 className="text-sm font-semibold tracking-wide">Valuation reference</h3>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="border-b border-line/60 pb-4">
          <p className="text-xs text-ink-muted">Fair value</p>
          <AnimatedNumber
            value={fairValue ?? 0}
            format={(v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            className="text-2xl font-semibold"
          />
        </div>
        <div className="border-b border-line/60 pb-4">
          <p className="text-xs text-ink-muted">Target price (12m)</p>
          <AnimatedNumber
            value={targetPrice ?? 0}
            format={(v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            className="text-2xl font-semibold"
          />
        </div>
      </div>
    </div>
  );
}
