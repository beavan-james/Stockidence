import { Link, useParams } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useModelWeights, useRating } from "@/hooks/queries";
import { adviceLabel, adviceStyle, formatMoney, titleCaseCategory } from "@/lib/format";
import type { RatingSource } from "@/types/api";
import { cn } from "@/lib/utils";

const SOURCE_COPY: Record<RatingSource, string> = {
  warehouse: "",
  refreshing: "Refreshing — showing the previous snapshot while the pipeline recomputes",
  pending: "First computation queued — this fills in as soon as the pipeline finishes",
  demo: "Sample data — the warehouse isn't reachable right now",
};

function SourceNotice({ source }: { source: RatingSource }) {
  const copy = SOURCE_COPY[source];
  if (!copy) return null;
  const live = source === "pending" || source === "refreshing";
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-lg border px-4 py-2.5 text-xs",
        live ? "border-accent/30 bg-accent-dim text-accent-strong" : "border-line bg-raised text-ink-secondary",
      )}
    >
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
      {copy}
    </div>
  );
}

export function ProfilePage() {
  const symbol = useParams().symbol?.toUpperCase();
  const rating = useRating(symbol);
  const weights = useModelWeights();

  if (!symbol) return null;

  if (rating.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  if (rating.isError) {
    return (
      <Card>
        <CardContent className="space-y-3 p-8 text-center">
          <p className="text-sm text-ink">{rating.error.message}</p>
          <Link to="/" className="text-xs text-accent hover:text-accent-strong">
            ← Back to Discover
          </Link>
        </CardContent>
      </Card>
    );
  }

  const r = rating.data!;

  return (
    <div className="space-y-4">
      <SourceNotice source={r.source} />

      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-10 gap-y-6 p-6">
          <div className="min-w-48">
            <h1 className="num text-lg font-semibold">{r.ticker}</h1>
            <p className="text-sm text-ink-secondary">{r.company_name || "—"}</p>
          </div>

          <div>
            <span
              className={cn(
                "inline-flex rounded-lg border px-3 py-1 text-sm font-medium",
                adviceStyle(r.advice),
              )}
            >
              {adviceLabel(r.advice)}
            </span>
          </div>

          <div>
            <p className="text-xs text-ink-muted">Confidence</p>
            <p className="num text-3xl font-semibold tracking-tight">
              {r.confidence_score.toFixed(1)}
            </p>
          </div>

          <div>
            <p className="text-xs text-ink-muted">Volatility</p>
            <p className="num text-3xl font-semibold tracking-tight">
              {r.volatility_score.toFixed(1)}
            </p>
          </div>

          {r.buy_plan && (
            <div>
              <p className="text-xs text-ink-muted">Buy plan</p>
              <p className="num text-sm text-ink">
                {formatMoney(r.buy_plan.advised_buy_price)} → stop{" "}
                {formatMoney(r.buy_plan.stop_loss_price)}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Score breakdown</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 pt-3">
          {weights.data?.map((w) => {
            const cat = r.categories.find((c) => c.category === w.category);
            return (
              <div key={w.category} className="flex items-center gap-4 text-sm">
                <span className="w-24 shrink-0 text-ink-secondary">
                  {titleCaseCategory(w.category)}
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${cat ? Math.max(cat.score, 2) : 0}%` }}
                  />
                </div>
                <span className="num w-12 text-right text-ink">
                  {cat ? cat.score.toFixed(0) : "—"}
                </span>
                <span className="num w-14 text-right text-xs text-ink-muted">
                  ×{w.weight.toFixed(2)}
                </span>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
