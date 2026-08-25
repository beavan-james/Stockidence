import { useMemo, useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { useComponentSpec } from "@/hooks/queries";
import { categoryColor, categoryLabel, scoreColor } from "@/lib/viz";
import type { ComponentScore } from "@/types/api";
import { cn } from "@/lib/utils";

const CATEGORY_ORDER = ["valuation", "trend", "sentiment", "moat", "volatility"] as const;

function SubScoreRow({ component }: { component: ComponentScore }) {
  const spec = useComponentSpec().data?.[component.component];
  const color = categoryColor(component.category);
  return (
    <div className="space-y-1.5 border-b border-line/60 pb-3 last:border-none">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{spec?.label ?? component.component}</span>
        <span className="num rounded-full px-2 py-0.5 text-xs" style={{ color: scoreColor(component.score), backgroundColor: `${scoreColor(component.score)}14` }}>
          {component.score.toFixed(0)} / 100
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-raised">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(component.score, 2)}%`, backgroundColor: color }}
        />
      </div>
      <p className="text-[11px] text-ink-muted">
        {spec?.sources}
        {" · "}
        <span className="num">{(component.weight * 100).toFixed(0)}% weight</span>
      </p>
      <p className="text-[11px] italic text-ink-muted/80">{spec?.direction}</p>
    </div>
  );
}

/** Collapsible per-category sub-scores with provenance and direction rules. */
export function SubScoreDetail({ components }: { components: ComponentScore[] }) {
  const [open, setOpen] = useState(false);

  const grouped = useMemo(() => {
    return CATEGORY_ORDER.map((category) => ({
      category,
      rows: components
        .filter((c) => c.category === category)
        .sort((a, b) => b.weight - a.weight),
    })).filter((g) => g.rows.length > 0);
  }, [components]);

  if (grouped.length === 0) return null;

  return (
    <Card>
      <CardContent className="p-6">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between text-left"
        >
          <div>
            <h3 className="font-semibold tracking-tight">Sub-score detail</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              The sub-scores behind each category. Volatility is reported separately and is
              never blended into the rating.
            </p>
          </div>
          <span className={cn("text-ink-muted transition-transform", open && "rotate-180")}>
            ▾
          </span>
        </button>

        {open && (
          <div className="mt-5 space-y-6">
            {grouped.map(({ category, rows }) => (
              <section key={category} className="space-y-3">
                <header className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: categoryColor(category) }}
                  />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-ink-secondary">
                    {categoryLabel(category)}
                  </h4>
                </header>
                <div className="space-y-3">
                  {rows.map((c, i) => (
                    <div
                      key={`${c.category}-${c.component}`}
                      className="anim-rise"
                      style={{ animationDelay: `${i * 45}ms` }}
                    >
                      <SubScoreRow component={c} />
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
