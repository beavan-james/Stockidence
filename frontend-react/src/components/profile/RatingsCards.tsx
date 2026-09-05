import { AnimatedNumber } from "@/components/ui/AnimatedNumber";
import { Scale } from "lucide-react";

/** Fair value anchor. Always rendered once the rating loads — a missing
 * value (thin fundamentals on a fresh ticker) shows as "—", never $0.00. */
export function ValuationReference({
  fairValue,
}: {
  fairValue: number | null;
}) {
  return (
    <div className="anim-rise space-y-4" style={{ animationDelay: "80ms" }}>
      <div className="flex items-center gap-2 text-accent">
        <Scale size={18} />
        <h3 className="text-sm font-semibold tracking-wide">Valuation reference</h3>
      </div>
      <div className="border-b border-line/60 pb-4">
        <p className="text-xs text-ink-muted">Fair value</p>
        {fairValue != null ? (
          <AnimatedNumber
            value={fairValue}
            format={(v) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
            className="text-2xl font-semibold"
          />
        ) : (
          <p className="num text-2xl font-semibold text-ink-muted">—</p>
        )}
      </div>
    </div>
  );
}
