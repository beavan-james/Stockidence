import { Skeleton } from "@/components/ui/skeleton";
import { useTechnicals } from "@/hooks/queries";
import { cn } from "@/lib/utils";

interface StatDef {
  key: string;
  label: string;
  hint: string;
  format: (v: number) => string;
}

const money = (v: number) =>
  `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const num2 = (v: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const compact = (v: number) =>
  Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(v);

const GROUPS: { title: string; stats: StatDef[] }[] = [
  {
    title: "Trend",
    stats: [
      { key: "sma_20", label: "SMA 20", hint: "Price above = short-term uptrend", format: money },
      { key: "sma_50", label: "SMA 50", hint: "Medium-term trend level", format: money },
      { key: "sma_200", label: "SMA 200", hint: "Long-term bull/bear line", format: money },
      { key: "ema_12", label: "EMA 12", hint: "Fast average, reacts quickly", format: money },
      { key: "ema_26", label: "EMA 26", hint: "Slow average, MACD baseline", format: money },
      { key: "macd", label: "MACD", hint: "Above zero = bullish momentum", format: num2 },
      { key: "macd_signal", label: "MACD signal", hint: "MACD above it = buy pressure", format: num2 },
      { key: "macd_hist", label: "MACD histogram", hint: "Expanding = momentum building", format: num2 },
      { key: "adx_14", label: "ADX 14", hint: "> 25 = strong trend either way", format: num2 },
      { key: "plus_di_14", label: "+DI", hint: "Above −DI = buyers in charge", format: num2 },
      { key: "minus_di_14", label: "−DI", hint: "Above +DI = sellers in charge", format: num2 },
    ],
  },
  {
    title: "Momentum",
    stats: [
      { key: "rsi_14", label: "RSI 14", hint: "> 70 overbought · < 30 oversold", format: num2 },
      { key: "stoch_k_14", label: "Stoch %K", hint: "> 80 overbought · < 20 oversold", format: num2 },
      { key: "stoch_d_14", label: "Stoch %D", hint: "K crossing above D = momentum up", format: num2 },
      { key: "cci_20", label: "CCI 20", hint: "> +100 overbought · < −100 oversold", format: num2 },
    ],
  },
  {
    title: "Volatility & bands",
    stats: [
      { key: "atr_14", label: "ATR 14", hint: "Average daily range in dollars", format: money },
      { key: "bb_upper_20", label: "Bollinger upper", hint: "Price near it = stretched up", format: money },
      { key: "bb_mid_20", label: "Bollinger middle", hint: "20-day mean, pullback magnet", format: money },
      { key: "bb_lower_20", label: "Bollinger lower", hint: "Price near it = stretched down", format: money },
      { key: "high_52w", label: "52-week high", hint: "Trailing 252-day peak", format: money },
      { key: "low_52w", label: "52-week low", hint: "Trailing 252-day trough", format: money },
      { key: "stddev_252", label: "Realized vol (1y)", hint: "Annualized price variability", format: num2 },
      {
        key: "max_drawdown_252",
        label: "Max drawdown (1y)",
        hint: "Worst peak-to-trough slide",
        format: (v) => `${(v * 100).toFixed(1)}%`,
      },
    ],
  },
  {
    title: "Volume",
    stats: [
      { key: "obv", label: "OBV", hint: "Rising with price = confirmed move", format: compact },
      { key: "ad", label: "A/D line", hint: "Divergence from price = caution", format: compact },
    ],
  },
];

/** Raw technical statistics — the numbers behind the old sub-scores, no scoring. */
export function TechnicalStats({ ticker }: { ticker: string }) {
  const stats = useTechnicals(ticker);

  if (stats.isPending) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-40" />
      </div>
    );
  }

  const indicators = stats.data?.indicators;
  if (!indicators) return null;

  return (
    <div className="anim-rise space-y-6" style={{ animationDelay: "140ms" }}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold tracking-tight">Technical statistics</h3>
        {stats.data?.as_of && (
          <span className="text-xs text-ink-muted">As of {stats.data.as_of}</span>
        )}
      </div>
        {GROUPS.map((g) => (
          <section key={g.title} className="space-y-1">
            <h4 className="text-xs font-bold uppercase tracking-wider text-ink-secondary">
              {g.title}
            </h4>
            <dl>
              {g.stats.map((s) => {
                const v = indicators[s.key];
                return (
                  <div
                    key={s.key}
                    className="flex items-baseline justify-between gap-4 border-b border-line/60 py-2 text-sm last:border-none"
                  >
                    <dt className="shrink-0 font-medium">
                      {s.label}
                      <span className="ml-2 hidden text-[11px] font-normal text-ink-muted sm:inline">
                        {s.hint}
                      </span>
                    </dt>
                    <dd className={cn("num text-right", v == null && "text-ink-muted")}>
                      {v == null ? "—" : s.format(v)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        ))}
    </div>
  );
}
