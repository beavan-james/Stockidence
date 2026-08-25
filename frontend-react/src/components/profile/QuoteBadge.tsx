import { useQuote } from "@/hooks/queries";
import { cn } from "@/lib/utils";

/** Live quote chip for the profile header: last price + change vs close. */
export function QuoteBadge({ ticker }: { ticker: string }) {
  const { data: quote } = useQuote(ticker);

  if (!quote?.price) return null;

  const change =
    quote.price != null && quote.prev_close != null
      ? quote.price - quote.prev_close
      : null;
  const changePct =
    change != null && quote.prev_close ? (change / quote.prev_close) * 100 : null;
  const gain = (change ?? 0) >= 0;

  return (
    <div className="flex items-baseline gap-2">
      <span className="num text-lg font-semibold">${quote.price.toFixed(2)}</span>
      {change != null && changePct != null && (
        <span className={cn("num text-sm font-medium", gain ? "text-gain" : "text-loss")}>
          {gain ? "+" : ""}
          {change.toFixed(2)} ({gain ? "+" : ""}
          {changePct.toFixed(2)}%)
        </span>
      )}
    </div>
  );
}
