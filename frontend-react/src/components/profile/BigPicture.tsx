import { Snowflake } from "@/components/profile/Snowflake";
import { Card, CardContent } from "@/components/ui/card";
import { adviceLabel, adviceStyle } from "@/lib/format";
import type { CategoryScore } from "@/types/api";

interface BigPictureProps {
  confidence: number;
  volatility: number;
  advice: string;
  asOf: string;
  categories: CategoryScore[];
}

function formatComputedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `Computed ${date.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}`;
}

/** Radar + verdict panel: what the model thinks, in one glance. */
export function BigPicture({ categories, ...scores }: BigPictureProps) {
  return (
    <Card>
      <CardContent className="grid items-center gap-10 p-6 md:grid-cols-2">
        <div className="flex justify-center">
          <Snowflake categories={categories} />
        </div>
        <div className="space-y-5">
          <p className="text-xs font-semibold tracking-widest text-ink-muted">
            THE BIG PICTURE
          </p>
          <span
            className={`inline-flex w-fit rounded-lg border px-3 py-1 text-sm font-medium ${adviceStyle(scores.advice)}`}
          >
            {adviceLabel(scores.advice)}
          </span>
          <div className="flex gap-10">
            <div>
              <p className="text-xs text-ink-muted">Confidence</p>
              <p className="num text-4xl font-semibold tracking-tight">
                {scores.confidence.toFixed(1)}
              </p>
              <p className="num text-[11px] text-ink-muted">out of 100</p>
            </div>
            <div>
              <p className="text-xs text-ink-muted">Volatility</p>
              <p className="num text-4xl font-semibold tracking-tight">
                {scores.volatility.toFixed(1)}
              </p>
              <p className="num text-[11px] text-ink-muted">separate score</p>
            </div>
          </div>
          {scores.asOf && (
            <p className="num text-xs text-ink-muted">{formatComputedAt(scores.asOf)}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
