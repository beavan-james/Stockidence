import { Card, CardContent } from "@/components/ui/card";
import { Scale, Target } from "lucide-react";
import { formatMoney, holdingStyleLabel } from "@/lib/format";

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
    <Card>
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center gap-2 text-accent">
          <Scale size={18} />
          <h3 className="text-sm font-semibold tracking-wide">Valuation reference</h3>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="text-xs text-ink-muted">Fair value</p>
            <p className="num text-2xl font-semibold">{formatMoney(fairValue)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-muted">Target price (12m)</p>
            <p className="num text-2xl font-semibold">{formatMoney(targetPrice)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/** Entry / stop / horizon for buy-rated tickers (MODEL.md contract). */
export function ExecutionPlan({
  advisedBuyPrice,
  stopLossPrice,
  holdingStyle,
}: {
  advisedBuyPrice: number;
  stopLossPrice: number;
  holdingStyle: string;
}) {
  const risk = advisedBuyPrice ? ((advisedBuyPrice - stopLossPrice) / advisedBuyPrice) * 100 : null;

  return (
    <Card className="border-accent/25 bg-accent-dim/40">
      <CardContent className="space-y-4 p-6">
        <div className="flex items-center gap-2 text-accent-strong">
          <Target size={18} />
          <h3 className="text-sm font-semibold tracking-wide">Execution plan</h3>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-ink-muted">Advised buy price</p>
            <p className="num text-2xl font-semibold">{formatMoney(advisedBuyPrice)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-muted">Stop-loss price</p>
            <p className="num text-2xl font-semibold text-loss">{formatMoney(stopLossPrice)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-muted">Holding style</p>
            <p className="text-lg font-semibold">{holdingStyleLabel(holdingStyle)}</p>
          </div>
        </div>
        {risk != null && (
          <p className="text-xs text-ink-secondary">
            Planned risk per share:{" "}
            <span className="num">{risk.toFixed(1)}%</span> below entry at the stop.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
