# Ticker Page: Fair Value & Technical Statistics

The ticker profile page (`/stocks/:symbol`) shows no ratings, advice, scores,
or buy plans. It shows three things: who the company is (profile + live
quote), what the stock is worth (fair value + 12-month target), and the raw
technical statistics those numbers sit alongside.

## Page sections

1. **Header** — logo, ticker, company name, live quote badge
   (`GET /api/quote/{ticker}`), portfolio button. A source notice reports
   `pending` (first computation queued), `refreshing` (snapshot older than a
   day, recompute launched), or `demo` (warehouse unreachable).
2. **Valuation reference** — fair value + 12-month target price
   (`GET /api/rating/{ticker}` → `fair_value`, `target_price`).
3. **Technical statistics** — raw indicator values grouped Trend / Momentum /
   Volatility & bands / Volume (`GET /api/technicals/{ticker}`), each with the
   latest bar date as `as_of`. No scoring, no 0–100 normalization.

## Fair value methodology

Fair value = blended DCF + comparables. Deterministic; assumptions are
centralized constants in the scoring module
(`src/stockidence/mart/scoring.py`, `FAIR_VALUE`).

**DCF leg (50%):**
1. Trailing owner FCF = OperatingCashFlow − CapEx (Financials As Reported XBRL concepts, TTM).
2. Stage-1 growth g = forward EPS growth (forward estimate from the earnings calendar annualized ×4; fallback to trailing EPS growth from EPS Surprises actuals, then to a proxy) (cap config, e.g. 20%); terminal growth g_ter = 2% (config).
3. Discount rate r = CAPM: risk-free (config, ~4%) + Beta × market premium (config, 5%). WACC proxies initially.
4. Firm value = Σ FCF·(1+g)^t/(1+r)^t over 5yr + terminal value / (1+r)^5; TV = FCF₅·(1+g_ter)/(r − g_ter).
5. Equity value = firm value − net debt (Balance Sheet concepts from Financials As Reported). Per-share = equity / shares outstanding (Company Profile 2 `shareOutstanding`).

**Comparables leg (50%):** "Comparable" = the company against its **own 3-5yr historical median multiples** (this repo's sources don't give a clean peer universe; Peers-based multiples are an optional later enrichment).
1. P/E: historical median P/E × forward EPS (forward estimate from earnings calendar)
2. EV/EBITDA: historical median EV/EBITDA × forward EBITDA (Basic Financials metrics)
3. P/S: historical median P/S × revenue per share (Basic Financials)
Fair value(comps) = mean of the three (nulls dropped), outliers clamped.

**Blend:** fair value = 0.5 × DCF + 0.5 × comps. Sanity clamp vs 52-week range (52-week high/low from Basic Financials) — never more than X× from current price (config).

## Target price methodology

Target price = **forward fair value** — fair value grown at expected 12-month earnings growth:

```
target = fairValue × (1 + g_fwd)
```

`g_fwd` = forward EPS growth (earnings-calendar estimate or trailing-EPS fallback), clamped to a config range (e.g. −20%..+30%). The **confidence rating** judges the gap between current price and *fair value*; the **target price** is the 12-month horizon expectation shown alongside the rating.

## Technical statistics

All values are end-of-day derivations from the cleaned daily bars
(`staging.stg_prices_daily`, Twelve Data `time_series`, split-adjusted),
computed in the mart layer — never fetched from a premium indicator API.
Served as the newest row of `mart.m_technical_indicators` plus 52-week
context from `mart.m_advanced_analytics`.

### Trend

| Stat | Meaning |
| ---- | ------- |
| SMA 20 / 50 / 200 | Simple moving averages; price above = uptrend on that horizon |
| EMA 12 / 26 | Exponential averages; MACD baseline |
| MACD / signal / histogram | EMA12−EMA26, its signal line, and the difference; above zero / expanding = bullish momentum |
| ADX 14 | Trend strength; > 25 = strong trend either way |
| +DI / −DI | Directional indexes; whichever is higher holds the tape |

### Momentum

| Stat | Meaning |
| ---- | ------- |
| RSI 14 | > 70 overbought · < 30 oversold |
| Stoch %K / %D | > 80 overbought · < 20 oversold; K crossing above D = momentum up |
| CCI 20 | > +100 overbought · < −100 oversold |

### Volatility & bands

| Stat | Meaning |
| ---- | ------- |
| ATR 14 | Average daily range in dollars |
| Bollinger upper / middle / lower (20) | 20-day mean ± bands; price near a band = stretched |
| 52-week high / low | Trailing 252-day peak / trough |
| Realized vol (1y) | Annualized price variability (stddev_252) |
| Max drawdown (1y) | Worst peak-to-trough slide |

### Volume

| Stat | Meaning |
| ---- | ------- |
| OBV | On-balance volume; rising with price = confirmed move |
| A/D line | Accumulation/distribution; divergence from price = caution |

## Data & API mapping

| Page section | API | Warehouse source |
| ------------ | --- | ---------------- |
| Header quote | `GET /api/quote/{ticker}` | `raw.raw_quotes` (TTL ~1 min) |
| Fair value + target | `GET /api/rating/{ticker}` (`fair_value`, `target_price`) | `m_confidence_ratings` snapshot |
| Technical statistics | `GET /api/technicals/{ticker}` | `m_technical_indicators` + `m_advanced_analytics`, latest row |

## Pipeline internals (not surfaced)

The deterministic scoring engine (`mart/scoring.py`: category weights,
sub-scores, rating bands, valuation override, buy plans) still runs in the
pipeline — fair value and target price are computed inside `score_ticker` —
but ratings, advice, sub-scores, and buy plans are not displayed anywhere in
the UI. The ranking model that powers the Model page is specified separately
in [`Model/README.md`](Model/README.md).
