# Model Overview
---
## Categories

| Category   | Description                                                                                                                   |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Valuation  | Is the stock priced correctly relative to its fundamentals? (DCF/comparables vs. current price)                               |
| Trend      | Is the stock currently moving up or down, and how strongly? (SMA/EMA/ADX)                                                     |
| Sentiment  | Does the market/news currently feel good or bad about it? (News sentiment, analyst recs)                                      |
| Moat       | The stock/companies lasting competitive advantage over rivals                                                                 |
| Volatility | How risky/unstable is it right now? (ATR/BBANDS — this feeds a separate volatility score, not the buy/sell confidence itself) |
---
## Philosophy

1. **Valuation is king**: If the stock is overvalued, it doesn't matter if it's trending up or has good sentiment, it's still a bad buy. Conversely, if it's undervalued, it may be a good buy even if it's trending down or has bad sentiment.
2. **Trend and Sentiment are secondary**: These factors can help you time your entry/exit, but they don't override valuation. A stock can be trending down but still be a strong buy if it's undervalued.
3. **Moat is tertiary**: A strong moat (competitive advantage) can make a stock more resilient to market fluctuations and give it a better long-term outlook.
4. **Volatility is separate**: Volatility is important for risk management, but it doesn't directly affect the buy/sell confidence rating. Instead, it feeds into a separate volatility score that can help inform your position sizing and stop-loss levels.
---
## Initial Model Weighting

| Category  | Weight |
| --------- | ------ |
| Valuation | 52%    |
| Trend     | 21%    |
| Sentiment | 21%    |
| Moat      | 6%     |
---
## API's
### Valuation API's
**Daily**
**Weekly**
**Monthly**
**Company Overview**
**Income Statement**
**Balance Sheet**
**Cash Flow**
**Earnings Estimate**
**EPS Surprises**
**Basic Financials**
**Financials As Reported**
**Time Series**
**Company Profile 2**

### Trend API's
**Company Overview** (use data from valuation call)
**Insider Sentiment**
**Daily**
**Weekly**
**Monthly**
**SMA**
**EMA**
**STOCH**
**RSI**
**ADX**
**CCI**
**AD**
**OBV**

### Sentiment API's
**Company Overview** (use data from valuation call)
**News & Sentiments**
**Company News** (Currently unused in purely deterministic model, but could be used for LLM layer)
**Insider Sentiment** (Use data from trend call)
**Recommendation Trends**
**Earnings Call Transcript**

### Moat API's
**Peers**

### Volatility API's
**Advanced Analytics (e.g., total return, variance, auto-correlation, etc.)**
**BBANDS**
**ATR**

---
## Scoring

Each category scores 0-100. Final confidence score = weighted sum. All sub-scores are deterministic, rule-based, and normalized to 0-100.

| Category   | Weight | Output role                              |
| ---------- | ------ | ----------------------------------------- |
| Valuation  | 52%    | Confidence rating (gating/override)       |
| Trend      | 21%    | Confidence rating (entry/exit timing)     |
| Sentiment  | 21%    | Confidence rating (market psychology)     |
| Moat       | 6%     | Confidence rating (long-term resilience)  |
| Volatility | —      | Separate score + stop-loss / holding style |

### Rating mapping (config-driven thresholds)

| Confidence score | Rating        |
| ---------------- | ------------- |
| >= 75            | Strong Buy    |
| 60 - 74          | Buy           |
| 40 - 59          | Hold          |
| 25 - 39          | Sell          |
| < 25             | Strong Sell   |

**Valuation override:** consistent with "valuation is king" — if the Valuation score < 35, cap the final rating at Hold no matter how good trend/sentiment are. If Valuation > 70, floor the final rating at Hold (a genuinely cheap stock can't be killed by weak short-term trend/sentiment). Ranges provisional.

### Valuation (52%)

Fair value (below) is computed and shown to the user, but the **score is a slightly different composite** — how cheap/expensive the stock looks on its fundamentals, only partly driven by fair value.

| Sub-score                         | Source fields (API.md Valuation Metrics)                                | Rule (simplified)                                                     | Weight |
| --------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------ |
| Discount to fair value            | Market cap + price vs fair value                                        | 1 - (price / fairValue) — larger gap to undervalued = higher           | 40%    |
| Historical P/E percentile         | Company Overview (PERatio), Daily/Weekly/Monthly + EPS history          | current P/E vs its own 3-5yr P/E band — below median = cheap           | 20%    |
| Forward vs trailing P/E gap       | Company Overview (TrailingPE, ForwardPE), Earnings Estimate             | forward < trailing → market expects growth → positive                  | 10%    |
| PEG                              | Company Overview (PEGRatio), Earnings Estimate                          | PEG < 1 → 80+, PEG 1-2 → 50, PEG > 2.5 → 20                           | 15%    |
| Multiple quality vs own history   | Company Overview (P/S, EV/EBITDA, P/B, EV/Revenue), NetProfitMargin     | P/S vs margin + EV/EBITDA vs historical median → cheap on quality      | 10%    |
| Recent EPS surprise momentum      | EPS Surprises (surprisePercent, last 4 quarters)                        | avg recent beats vs older → positive                                   | 5%     |

### Trend (21%)

| Sub-score                   | Sources                            | Direction (positive = buy-friendly)                                    | Weight |
| --------------------------- | ---------------------------------- | ---------------------------------------------------------------------- | ------ |
| Price vs SMA50/SMA200       | SMA, Company Overview (50/200DMA)  | price > SMA → +; golden/death cross alignment                          | 30%    |
| MACD (derived in staging)   | EMA12/EMA26 from Daily             | MACD > signal + histogram expanding → +                               | 20%    |
| ADX trend strength +DI/-DI  | ADX                                | ADX > 25 and +DI > -DI → strong uptrend → +                          | 15%    |
| RSI momentum/entry          | RSI                                | 30-50 in uptrend → 70+, > 70 overbought → 20-30 (mean-reverting)      | 15%    |
| Stochastic + CCI            | STOCH, CCI                         | 20-40 rising → +; > 80 → -                                           | 10%    |
| Volume confirmation         | OBV, AD                            | OBV/AD trending with price → +; divergence → -                        | 10%    |

### Sentiment (21%)

| Sub-score                          | Sources                                                    | Weight |
| ---------------------------------- | ----------------------------------------------------------- | ------ |
| News sentiment (last 2 weeks)      | Market News + Company News (avg sentiment, -1..1)           | 30%    |
| Analyst consensus                  | Company Overview analyst ratings + Recommendation Trends    | 25%    |
| Insider sentiment                  | Insider Sentiment (mspr trend, change)                      | 20%    |
| Earnings call transcript tone      | Earnings Call Transcript (avg segment sentiment)            | 15%    |
| Earnings surprise trend            | EPS Surprises (reused from valuation, not double-counted)   | 10%    |

### Moat (6%)

Deterministic proxies, no manual judgment. Benchmark against Peers (Finnhub) where available, else vs the company's own history.

| Sub-score                 | Source                                        | Weight |
| ------------------------- | --------------------------------------------- | ------ |
| Margin quality            | Income Statement (gross/operating/net margin level + 3-5yr stability) | 35% |
| Return on capital         | Balance Sheet + Income (ROE, ROA; ROIC proxy) | 30%    |
| Growth consistency        | Income Statement + Monthly (revenue/EPS stability) | 20%    |
| Scale advantage           | Company Overview (market cap vs peer median)  | 15%    |

### Volatility (separate score, not in confidence rating)

Higher = riskier. Feeds holding-style advice + stop-loss sizing.

| Sub-score              | Source                                     | Weight |
| ---------------------- | ------------------------------------------ | ------ |
| Realized vol           | Advanced Analytics (STDDEV annualized, 1yr) | 30%    |
| ATR%                   | ATR / price                                | 30%    |
| BBANDS bandwidth       | BBANDS bandwidth percentile vs 1yr history | 25%    |
| Beta                   | Company Overview (Beta)                    | 15%    |

Volatility bands → holding-style advice (provisional):
- Volatility score < 25 → long-term hold
- 25 - 60 → swing trade
- > 60 → day trade

---
## Methodology

### Fair Value Methodology

Fair value = blended DCF + comparables. Shown to the user; feeds the Valuation score and the target price. All inputs deterministic, from fields in API.md Valuation Metrics. Assumptions are config-driven, never hardcoded.

**DCF leg (50%):**
1. Trailing owner FCF = OperatingCashFlow − CapEx (Cash Flow, TTM).
2. Stage-1 growth g = forward EPS growth from Earnings Estimate (cap config, e.g. 20%); terminal growth g_ter = 2% (config).
3. Discount rate r = CAPM: risk-free (config, ~4%) + Beta × market premium (config, 5%). WACC proxies initially.
4. Firm value = Σ FCF·(1+g)^t/(1+r)^t over 5yr + terminal value / (1+r)^5; TV = FCF₅·(1+g_ter)/(r − g_ter).
5. Equity value = firm value − net debt (Balance Sheet). Per-share = equity / shares outstanding (Company Overview SharesOutstanding).

**Comparables leg (50%):** "Comparable" = the company against its **own 3-5yr historical median multiples** (this repo's sources don't give a clean peer universe; Peers-based multiples are an optional later enrichment).
1. P/E: historical median P/E × forward EPS (Earnings Estimate)
2. EV/EBITDA: historical median EV/EBITDA × forward EBITDA (Income Statement)
3. P/S: historical median P/S × revenue per share
Fair value(comps) = mean of the three (nulls dropped), outliers clamped.

**Blend:** fair value = 0.5 × DCF + 0.5 × comps. Sanity clamp vs 52-week range (52WeekHigh/Low) — never more than X× from current price (config).

### Target Pricing Methodology

Target price = **forward fair value** — fair value grown at expected 12-month earnings growth:

```
target = fairValue × (1 + g_fwd)
```

`g_fwd` = forward EPS growth (Earnings Estimate), clamped to a config range (e.g. −20%..+30%). The **confidence rating** judges the gap between current price and *fair value*; the **target price** is the 12-month horizon expectation shown alongside the rating.

### Advised Buy Price, Stop-Loss & Holding Style (Buy/Strong Buy only)

1. **Advised buy price** = min(current price, fairValue × (1 − margin_of_safety)) — margin of safety default 15% (config). Price ≤ buy price → buy now; above → wait for pullback to that level.
2. **Stop-loss** = advised buy price − k × ATR, k scaled by holding style: day trade 1.0, swing 1.5, long-term 2.0 (provisional; floored so low-priced stocks don't get absurdly tight stops).
3. **Holding style** from the volatility bands above. Long-term holdings track the 12m target; swing/day trades are managed off the stop/ATR, not fair value.

All weights, thresholds, growth caps, margins of safety, and ATR multipliers are **provisional spec, not locked** — centralize them as constants so backtesting can tune them without touching scoring logic.