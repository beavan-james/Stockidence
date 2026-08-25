/** Category identity colors and score→color mapping for data viz. */

export const CATEGORY_COLORS: Record<string, string> = {
  valuation: "#818cf8",
  trend: "#22d3ee",
  sentiment: "#fbbf24",
  moat: "#34d399",
  volatility: "#94a3b8",
};

export const CATEGORY_LABELS: Record<string, string> = {
  valuation: "Valuation",
  trend: "Trend",
  sentiment: "Sentiment",
  moat: "Moat",
  volatility: "Volatility (separate)",
};

export function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? "#94a3b8";
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.charAt(0).toUpperCase() + category.slice(1);
}

/** Score bands mirror the model's qualitative read of a 0-100 score. */
export function scoreColor(score: number): string {
  if (score >= 65) return "#34d399";
  if (score >= 45) return "#fbbf24";
  return "#f87171";
}
