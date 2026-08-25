/** Display formatting shared across pages. */

import type { Advice } from "@/types/api";

export function formatMoney(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  return `${value.toFixed(digits)}%`;
}

const ADVICE_STYLES: Record<Advice, string> = {
  STRONG_BUY: "text-gain border-gain/40 bg-gain/10",
  BUY: "text-gain border-gain/30 bg-gain/5",
  HOLD: "text-amber-300 border-amber-300/40 bg-amber-300/10",
  SELL: "text-loss border-loss/40 bg-loss/10",
  STRONG_SELL: "text-loss border-loss/50 bg-loss/15",
};

const ADVICE_LABELS: Record<Advice, string> = {
  STRONG_BUY: "Strong Buy",
  BUY: "Buy",
  HOLD: "Hold",
  SELL: "Sell",
  STRONG_SELL: "Strong Sell",
};

const NEUTRAL_ADVICE_STYLE = "text-ink-secondary border-line bg-raised";

export function adviceStyle(advice: string): string {
  return ADVICE_STYLES[advice as Advice] ?? NEUTRAL_ADVICE_STYLE;
}

export function adviceLabel(advice: string): string {
  return ADVICE_LABELS[advice as Advice] ?? advice.charAt(0) + advice.slice(1).toLowerCase();
}

const HOLDING_STYLE_LABELS: Record<string, string> = {
  long_term_hold: "Long-term hold",
  swing_trade: "Swing trade",
  day_trade: "Day trade",
};

export function holdingStyleLabel(style: string): string {
  return HOLDING_STYLE_LABELS[style] ?? style;
}

export function titleCaseCategory(category: string): string {
  return category.charAt(0).toUpperCase() + category.slice(1);
}
