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
## Model Weighting

**Current: v2 (2026-08), first backtest-informed revision.**

| Category  | v1 | v2 (current) |
| --------- | ----- | ------------ |
| Valuation | 52%   | **62%**      |
| Trend     | 21%   | **24%**      |
| Sentiment | 21%   | **10%**      |
| Moat      | 6%    | **4%**       |

v2 rationale — category sub-scores were correlated against realized 60d
forward returns on 327 train-window replays (2025-06..2026-02, 13 tickers,
date-block bootstrap CIs): valuation +0.38 [+0.31, +0.44], trend +0.05
[-0.07, +0.15], sentiment -0.30 [-0.39, -0.20], moat -0.25 [-0.32, -0.15].
Weight moved toward the only positive contributor; sentiment/moat halved,
not zeroed (single window, single regime). Trend kept as a stabilizer.

Honest limits of this evidence:
- Held-out validation (2026-03..2026-05) showed ~zero score↔return
  correlation under BOTH v1 and v2 — the edge is regime-dependent and no
  reweighting within current category definitions fixes that.
- The highest-confidence quintile underperforms quintile 4 in both windows
  (value-trap signature). A trend-confirmation guard for top ratings is a
  candidate scoring-logic change, not bundled into the weight pass.
- No Sell/Strong Sell fires naturally in this bull window; reachability is
  to be demonstrated via a documented stress case.

All weights remain provisional pending more history and bear-market data.
---
## API's
_(Marked "(not used)" when the endpoint has no ingestion path; see API.md for samples.)_

### Valuation API's
**EPS Surprises**
**Basic Financials**
**Financials As Reported**
**Earnings Calendar** (forward EPS estimates)
**Time Series** (Twelve Data, daily bars → P/E history)
**Company Profile 2** (share count)
**Company Overview** (not used — AV premium/free tier, replaced by Finnhub basic financials)
**Daily** (not used)
**Weekly** (not used)
**Monthly** (not used)
**Income Statement** (not used — replaced by Financials As Reported XBRL)
**Balance Sheet** (not used — replaced by Financials As Reported XBRL)
**Cash Flow** (not used — replaced by Financials As Reported XBRL)
**Earnings Estimate** (not used — forward EPS read from the earnings calendar)

### Trend API's
**Insider Sentiment**
**Technical indicators (SMA, EMA, STOCH, RSI, ADX, CCI, AD, OBV)** (derived in mart from daily bars, not API calls)
**Daily** (not used)
**Weekly** (not used)
**Monthly** (not used)
**Company Overview** (not used)

### Sentiment API's
**News & Sentiments**
**Insider Sentiment** (use data from trend call)
**Recommendation Trends**
**Earnings Call Transcript**
**Company News** (not used in purely deterministic model, but could be used for LLM layer)
**Company Overview** (not used)

### Moat API's
**Peers**
**Basic Financials** (margins, ROE/ROA from the valuation call)

### Volatility API's
**Beta** (Basic Financials)
**Advanced Analytics / BBANDS / ATR** (derived in mart from daily bars, not API calls)

---
## Scoring

Each category scores 0-100. Final confidence score = weighted sum. All sub-scores are deterministic, rule-based, and normalized to 0-100.

| Category   | Weight | Output role                              |
| ---------- | ------ | ----------------------------------------- |
| Valuation  | 62%    | Confidence rating (gating/override)       |
| Trend      | 24%    | Confidence rating (entry/exit timing)     |
| Sentiment  | 10%    | Confidence rating (market psychology)     |
| Moat       | 4%     | Confidence rating (long-term resilience)  |
| Volatility | —      | Separate score + stop-loss / holding style |

### Rating mapping (config-driven thresholds)

v2 bounds (2026-08): recalibrated to the score range the composite actually
produces (observed 43.7–69.1 over 431 replays — the original 75/60/40/25
left Sell/Strong Sell unreachable and Strong Buy never firing).

| Confidence score | Rating        |
| ---------------- | ------------- |
| >= 66            | Strong Buy    |
| 59 - 65          | Buy           |
| 50 - 58          | Hold          |
| 46 - 49          | Sell          |
| < 46             | Strong Sell   |

Train-window check (327 replays, 2025-06..2026-02): the Sell bucket realized
−2.9% mean / −2.0% median 60d forward return (38% up) vs Hold +5.4% and Buy
+13.5% — the low bands mark genuinely below-market names. Held-out window
was too regime-distorted to confirm; bounds provisional pending bear-market
data.

**Valuation override:** consistent with "valuation is king" — if the Valuation score < 35, cap the final rating at Hold no matter how good trend/sentiment are. If Valuation > 70, floor the final rating at Hold (a genuinely cheap stock can't be killed by weak short-term trend/sentiment). Ranges provisional.

### Valuation (62%)

Fair value (below) is computed and shown to the user, but the **score is a slightly different composite** — how cheap/expensive the stock looks on its fundamentals, only partly driven by fair value.

| Sub-score                         | Source fields (API.md Valuation Metrics)                                | Rule (simplified)                                                     | Weight |
| --------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------ |
| Discount to fair value            | Market cap + price vs fair value                                        | 1 - (price / fairValue) — larger gap to undervalued = higher           | 40%    |
| Historical P/E percentile         | Company Overview (PERatio), Daily/Weekly/Monthly + EPS history          | current P/E vs its own 3-5yr P/E band — below median = cheap           | 20%    |
| Forward vs trailing P/E gap       | Company Overview (TrailingPE, ForwardPE), Earnings Estimate             | forward < trailing → market expects growth → positive                  | 10%    |
| PEG                              | Company Overview (PEGRatio), Earnings Estimate                          | PEG < 1 → 80+, PEG 1-2 → 50, PEG > 2.5 → 20                           | 15%    |
| Multiple quality vs own history   | Company Overview (P/S, EV/EBITDA, P/B, EV/Revenue), NetProfitMargin     | P/S vs margin + EV/EBITDA vs historical median → cheap on quality      | 10%    |
| Recent EPS surprise momentum      | EPS Surprises (surprisePercent, last 4 quarters)                        | avg recent beats vs older → positive                                   | 5%     |

### Trend (24%)

| Sub-score                   | Sources                            | Direction (positive = buy-friendly)                                    | Weight |
| --------------------------- | ---------------------------------- | ---------------------------------------------------------------------- | ------ |
| Price vs SMA50/SMA200       | SMA, Company Overview (50/200DMA)  | price > SMA → +; golden/death cross alignment                          | 30%    |
| MACD (derived in mart)   | EMA12/EMA26 from Daily             | MACD > signal + histogram expanding → +                               | 20%    |
| ADX trend strength +DI/-DI  | ADX                                | ADX > 25 and +DI > -DI → strong uptrend → +                          | 15%    |
| RSI momentum/entry          | RSI                                | 30-50 in uptrend → 70+, > 70 overbought → 20-30 (mean-reverting)      | 15%    |
| Stochastic + CCI            | STOCH, CCI                         | 20-40 rising → +; > 80 → -                                           | 10%    |
| Volume confirmation         | OBV, AD                            | OBV/AD trending with price → +; divergence → -                        | 10%    |

### Sentiment (10%)

| Sub-score                          | Sources                                                    | Weight |
| ---------------------------------- | ----------------------------------------------------------- | ------ |
| News sentiment (last 2 weeks)      | Market News + Company News (avg sentiment, -1..1)           | 30%    |
| Analyst consensus                  | Company Overview analyst ratings + Recommendation Trends    | 25%    |
| Insider sentiment                  | Insider Sentiment (mspr trend, change)                      | 20%    |
| Earnings call transcript tone      | Earnings Call Transcript (avg segment sentiment)            | 15%    |
| Earnings surprise trend            | EPS Surprises (reused from valuation, not double-counted)   | 10%    |

### Moat (4%)

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

Fair value = blended DCF + comparables. Shown to the user; feeds the Valuation score and the target price. All inputs deterministic. Assumptions are centralized constants (fair-value config lives in the scoring module — provisional, not locked until backtested).

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

### Target Pricing Methodology

Target price = **forward fair value** — fair value grown at expected 12-month earnings growth:

```
target = fairValue × (1 + g_fwd)
```

`g_fwd` = forward EPS growth (earnings-calendar estimate or trailing-EPS fallback), clamped to a config range (e.g. −20%..+30%). The **confidence rating** judges the gap between current price and *fair value*; the **target price** is the 12-month horizon expectation shown alongside the rating.

### Advised Buy Price, Stop-Loss & Holding Style (Buy/Strong Buy only)

1. **Advised buy price** = min(current price, fairValue × (1 − margin_of_safety)) — margin of safety default 15% (config). Price ≤ buy price → buy now; above → wait for pullback to that level.
2. **Stop-loss** = advised buy price − k × ATR, k scaled by holding style: day trade 3.0, swing 4.5, long-term 6.0 (v2 2026-08: widened ×3 after trade-level backtesting — the original 1.0/1.5/2.0 stopped out ~84% of positions before any target could be reached, median trade −2.4%; at 3× the avg/trade went +1.4% → +13.5% train / +16.3% held-out with win rate 25%→73%. Floored so low-priced stocks don't get absurdly tight stops.)
3. **Holding style** from the volatility bands above. Long-term holdings track the 12m target; swing/day trades are managed off the stop/ATR, not fair value. Expected holding window for plan-based exits is up to ~120 trading days (~6 months) per the backtest's timeout horizon.

Backtesting further found that exiting at **fair value itself** (instead of the growth-extended target price) adds roughly +10pp avg/trade on top of the stop widening (+18.1% vs +13.5% train). Not yet adopted — it changes what "target price" means downstream. Candidate for v3.

All weights, thresholds, growth caps, margins of safety, and ATR multipliers are **provisional spec, not locked** — centralize them as constants so backtesting can tune them without touching scoring logic.