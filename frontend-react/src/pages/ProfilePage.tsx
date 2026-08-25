import { Link, useParams } from "react-router-dom";

import { BigPicture } from "@/components/profile/BigPicture";
import { ComputingScreen } from "@/components/profile/ComputingScreen";
import { QuoteBadge } from "@/components/profile/QuoteBadge";
import { ExecutionPlan, ValuationReference } from "@/components/profile/RatingsCards";
import { SubScoreDetail } from "@/components/profile/SubScoreDetail";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRating } from "@/hooks/queries";
import { adviceLabel, adviceStyle } from "@/lib/format";
import { categoryColor, categoryLabel } from "@/lib/viz";
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
        live
          ? "border-accent/30 bg-accent-dim text-accent-strong"
          : "border-line bg-raised text-ink-secondary",
      )}
    >
      {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
      {copy}
    </div>
  );
}

function ScoreBreakdown({
  categories,
}: {
  categories: { category: string; score: number; weight: number }[];
}) {
  return (
    <Card>
      <CardContent className="space-y-4 p-6">
        <h3 className="font-semibold tracking-tight">Score breakdown</h3>
        {categories.map((c) => (
          <div key={c.category} className="flex items-center gap-4 text-sm">
            <span className="w-24 shrink-0 text-ink-secondary">
              {categoryLabel(c.category).replace(" (separate)", "")}
            </span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-raised">
              <div
                className="h-full rounded-full transition-all duration-700"
                style={{
                  width: `${Math.max(c.score, 2)}%`,
                  backgroundColor: categoryColor(c.category),
                }}
              />
            </div>
            <span className="num w-16 text-right text-xs text-ink-muted">
              {(c.weight * 100).toFixed(0)}% weight
            </span>
            <span className="num w-8 text-right">{c.score.toFixed(0)}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function ProfilePage() {
  const symbol = useParams().symbol?.toUpperCase();
  const rating = useRating(symbol);

  if (!symbol) return null;

  if (rating.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-72" />
      </div>
    );
  }

  if (rating.isError) {
    return (
      <Card>
        <CardContent className="space-y-3 p-10 text-center">
          <p className="text-sm text-ink">{rating.error.message}</p>
          <Link to="/" className="text-xs text-accent hover:text-accent-strong">
            ← Back to Discover
          </Link>
        </CardContent>
      </Card>
    );
  }

  const r = rating.data;
  if (!r) return null;
  const loading = r.source === "pending" || r.source === "refreshing" || r.advice === "PENDING";

  return (
    <div className="space-y-4">
      <Link to="/" className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-accent">
        ← Back to Discover
      </Link>

      <SourceNotice source={r.source} />

      {loading ? (
        <ComputingScreen source={r.source} ticker={r.ticker} />
      ) : (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center justify-between gap-x-10 gap-y-4 p-6">
              <div className="flex items-center gap-4">
                {r.logo_url && (
                  <img src={r.logo_url} alt="" className="h-9 w-9 rounded-lg bg-raised object-contain" />
                )}
                <div>
                  <h1 className="num text-xl font-semibold tracking-tight">{r.ticker}</h1>
                  <p className="text-sm text-ink-secondary">{r.company_name || "—"}</p>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <QuoteBadge ticker={r.ticker} />
                <span
                  className={cn(
                    "inline-flex rounded-lg border px-3 py-1 text-sm font-medium",
                    adviceStyle(r.advice),
                  )}
                >
                  {adviceLabel(r.advice)}
                </span>
              </div>
            </CardContent>
          </Card>

          <BigPicture
            confidence={r.confidence_score}
            volatility={r.volatility_score}
            advice={r.advice}
            asOf={r.as_of}
            categories={r.categories}
          />

          <ValuationReference fairValue={r.fair_value} targetPrice={r.target_price} />

          <ScoreBreakdown categories={r.categories} />

          {r.buy_plan && (
            <ExecutionPlan
              advisedBuyPrice={r.buy_plan.advised_buy_price}
              stopLossPrice={r.buy_plan.stop_loss_price}
              holdingStyle={r.buy_plan.holding_style}
            />
          )}

          <SubScoreDetail components={r.components} />
        </>
      )}
    </div>
  );
}
