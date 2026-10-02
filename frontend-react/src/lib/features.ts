/**
 * Display metadata for the ranking model's 13 inputs (CORE13 in the
 * production notebook). Values arrive raw from the dataset: returns and
 * ratios-to-assets are fractions, stddev_252 is the 1-year standard
 * deviation of the closing price in dollars.
 */

type Format = "pct" | "ratio" | "usd";

interface FeatureMeta {
  label: string;
  group: "Momentum" | "Risk" | "Quality" | "Balance sheet";
  format: Format;
  /** One-line plain-English definition for the Model page. */
  help: string;
}

export const FEATURES: Record<string, FeatureMeta> = {
  return_12m: { label: "12-month return", group: "Momentum", format: "pct", help: "Price change over the last four quarters." },
  return_3m: { label: "3-month return", group: "Momentum", format: "pct", help: "Price change over the last quarter." },
  price_to_sma200: { label: "Price vs 200-day average", group: "Momentum", format: "ratio", help: "Close divided by its 200-day moving average." },
  distance_from_52wk_high: { label: "Distance from 52-week high", group: "Momentum", format: "pct", help: "How far the close sits below its 1-year high." },
  stddev_252: { label: "Price swing, 1 year", group: "Risk", format: "usd", help: "Standard deviation of the closing price over the last year." },
  max_drawdown_252: { label: "Worst drawdown, 1 year", group: "Risk", format: "pct", help: "Deepest fall from a running peak over the last year." },
  atr_pct: { label: "Average daily range", group: "Risk", format: "pct", help: "14-day average true range as a share of price." },
  roe: { label: "Return on equity", group: "Quality", format: "pct", help: "Quarterly net income over shareholders' equity." },
  roa: { label: "Return on assets", group: "Quality", format: "pct", help: "Quarterly net income over total assets." },
  fcf_to_assets: { label: "Free cash flow / assets", group: "Quality", format: "pct", help: "Operating cash flow minus capex, over total assets." },
  debt_equity: { label: "Debt to equity", group: "Balance sheet", format: "ratio", help: "Total liabilities over shareholders' equity." },
  current_ratio: { label: "Current ratio", group: "Balance sheet", format: "ratio", help: "Current assets over current liabilities." },
  cash_to_assets: { label: "Cash / assets", group: "Balance sheet", format: "pct", help: "Cash and equivalents over total assets." },
};

export function featureMeta(feature: string): FeatureMeta {
  return FEATURES[feature] ?? { label: feature, group: "Quality", format: "ratio", help: "" };
}

export function formatFeature(feature: string, value: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  switch (featureMeta(feature).format) {
    case "pct": {
      const pct = value * 100;
      const sign = pct > 0 && feature.startsWith("return") ? "+" : "";
      return `${sign}${pct.toFixed(Math.abs(pct) < 10 ? 1 : 0)}%`;
    }
    case "usd":
      return `$${value.toFixed(value < 100 ? 2 : 0)}`;
    default:
      return `${value.toFixed(2)}×`;
  }
}

/** Contributions are tiny raw margins; show them as points (×100). */
export function formatPoints(contribution: number): string {
  const pts = contribution * 100;
  return `${pts >= 0 ? "+" : "−"}${Math.abs(pts).toFixed(1)}`;
}
