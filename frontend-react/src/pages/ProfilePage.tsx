import { Link, useParams } from "react-router-dom";
import { useEffect } from "react";

import { ComputingScreen } from "@/components/profile/ComputingScreen";
import { QuoteBadge } from "@/components/profile/QuoteBadge";
import { ValuationReference } from "@/components/profile/RatingsCards";
import { TechnicalStats } from "@/components/profile/TechnicalStats";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRating } from "@/hooks/queries";
import { usePortfolio, addToPortfolio, isInPortfolio, removeFromPortfolio } from "@/hooks/portfolio";
import type { RatingSource } from "@/types/api";
import { cn } from "@/lib/utils";
import { Plus, Check } from "lucide-react";

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

function useDocumentTitle(title: string | undefined) {
  useEffect(() => {
    if (title) document.title = `${title} — Stockidence`;
    return () => {
      document.title = "Stockidence — Stock Confidence Rating";
    };
  }, [title]);
}

export function ProfilePage() {
  const symbol = useParams().symbol?.toUpperCase();
  const rating = useRating(symbol);
  usePortfolio();
  useDocumentTitle(symbol);

  if (!symbol) return null;

  const inPortfolio = isInPortfolio(symbol);

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
          <Link to="/discover" className="text-xs text-accent hover:text-accent-strong">
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
      <Link to="/discover" className="inline-flex items-center gap-1 text-xs text-ink-muted hover:text-accent">
        ← Back to Discover
      </Link>

      <SourceNotice source={r.source} />

      {loading ? (
        <ComputingScreen source={r.source} ticker={r.ticker} />
      ) : (
        <>
          <Card className="anim-rise">
            <CardContent className="flex flex-wrap items-center justify-between gap-x-10 gap-y-4 p-6">
              <div className="flex items-center gap-4">
                {r.logo_url && (
                  <img src={r.logo_url} alt="" className="h-9 w-9 rounded-lg bg-raised object-contain" />
                )}
                <div>
                  <h1 className="num title-glow text-xl font-semibold tracking-tight">{r.ticker}</h1>
                  <p className="text-sm text-ink-secondary">{r.company_name || "—"}</p>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <QuoteBadge ticker={r.ticker} />
                <button
                  onClick={() =>
                    inPortfolio ? removeFromPortfolio(symbol) : addToPortfolio(symbol)
                  }
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1 text-sm transition-colors",
                    inPortfolio
                      ? "border-accent/30 bg-accent/10 text-accent hover:bg-accent/20"
                      : "border-line bg-surface text-ink-secondary hover:border-accent/30 hover:text-ink",
                  )}
                >
                  {inPortfolio ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      In portfolio
                    </>
                  ) : (
                    <>
                      <Plus className="h-3.5 w-3.5" />
                      Add to portfolio
                    </>
                  )}
                </button>
              </div>
            </CardContent>
          </Card>

          <ValuationReference fairValue={r.fair_value} targetPrice={r.target_price} />

          <TechnicalStats ticker={r.ticker} />
        </>
      )}
    </div>
  );
}
