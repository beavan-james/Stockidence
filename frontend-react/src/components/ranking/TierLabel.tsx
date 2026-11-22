import { TIER_COLORS, TIER_NAMES } from "@/lib/tiers";

/** Tier as plain text behind a swatch of the colour that fifth glows in the
 *  home page's disc: the top fifth's text in a softened accent, the rest muted. */
export function TierLabel({ tier }: { tier: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] ${tier === 0 ? "text-accent/70" : "text-ink-muted"}`}
    >
      <i className="inline-block h-2 w-2 shrink-0" style={{ background: TIER_COLORS[tier] }} />
      {TIER_NAMES[tier]}
    </span>
  );
}
