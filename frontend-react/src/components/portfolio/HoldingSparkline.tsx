import { cn } from "@/lib/utils";

/** Minimal trend line for holding cards. Green/red by first→last move. */
export function HoldingSparkline({
  values,
  className,
}: {
  values: (number | null)[];
  className?: string;
}) {
  const clean = values.filter((v): v is number => v != null);
  if (clean.length < 2) return null;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const coords = clean
    .map((v, i) => `${(i / (clean.length - 1)) * 100},${28 - ((v - min) / span) * 24}`)
    .join(" ");
  const up = clean[clean.length - 1] >= clean[0];
  return (
    <svg
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      className={cn("h-12 w-full", className)}
    >
      <polyline
        points={coords}
        fill="none"
        stroke={up ? "#34d399" : "#f87171"}
        strokeWidth="2"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
