import { TIER_COLORS, TIER_NAMES } from "@/lib/tiers";

export function TierPill({ tier }: { tier: number }) {
  const color = TIER_COLORS[tier];
  return (
    <span
      className="inline-block whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs"
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 35%, transparent)`,
        background: `color-mix(in srgb, ${color} 12%, transparent)`,
      }}
    >
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
