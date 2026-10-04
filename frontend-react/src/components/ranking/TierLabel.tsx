import { TIER_COLORS, TIER_NAMES } from "@/lib/tiers";

/** Tier as plain text: the top fifth in the accent, the rest muted. */
export function TierLabel({ tier }: { tier: number }) {
  return (
    <span className={`whitespace-nowrap text-xs ${tier === 0 ? "text-accent" : "text-ink-muted"}`}>
      {TIER_NAMES[tier]}
    </span>
  );
}

export function TierLegend() {
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-muted">
      {TIER_NAMES.map((name, i) => (
        <span key={name} className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5" style={{ background: TIER_COLORS[i] }} />
          {name}
        </span>
      ))}
    </div>
  );
}
