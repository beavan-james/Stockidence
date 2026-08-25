# Stockidence — Stock Confidence Rating Pipeline
--- 
## What this is

A **stock confidence rating pipeline**. The scoring logic is
relatively deterministic — the focus is on the data ingestion and the app
itself rather than the algorithm. The scoring layer has since been
**backtested point-in-time and recalibrated once** on that evidence (see
[Backtesting & Validation](#backtesting--validation)).

**The problem it answers:** *"I want to buy this stock but don't know if it's a
good time, and I don't have time to research it."* The app outputs, for any
ticker:

- a **confidence rating** + advice (`strong buy / buy / hold / sell / strong sell`)
- a **separate volatility score**
- for buy-rated tickers: an **advised buy price**, **stop-loss price**, and
  **holding-style advice** (long-term hold / swing trade / day trade)
---
## How it's built

- **On-demand, not a fixed watchlist.** Users enter any ticker at request time.
  The pipeline can't rely on pre-scheduled batch loads for a static universe,
  so it needs a staleness-aware cache layer in front of the API calls: an
  on-demand request reuses recently-fetched data instead of re-hitting
  free-tier rate limits.
- **Orchestration:** Dagster (assets/jobs), with incrementals load design
  driven by watermark-based staleness gates per (source, ticker, endpoint).
- **Warehouse:** DuckDB, three-layer schema `raw → staging → mart`.
- **Caching:** staleness-aware cache in front of API calls; policy differs by
  data type (a quote is stale in minutes, an income statement in months).
- **Serving & UI:** FastAPI (`src/stockidence/api/`) exposes the mart layer as
  a typed REST API; a React + TypeScript SPA (`frontend-react/`) renders it.
  The UI reads the warehouse through that API — never the providers directly.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full data flow.

---
## Data Sources

Sources are deliberately limited to free tiers — rate limits are a problem the
caching layer exists to solve, not a problem to buy around.

| Source            | Used for                                                                                                                                                                            | Reference |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| **Finnhub**       | Company profile 2, basic & as-reported financials, EPS surprises, insider sentiment, recommendation trends, peers, IPO & earnings calendars, quote, stock symbol listing            |    [Finnhub API Documentation](https://finnhub.io/docs/api/introduction)     |
| **Twelve Data**   | Price time series (`interval=1day`, split-adjusted); weekly/monthly are resampled downstream in the warehouse, not fetched                                                          |    [Twelve Data API Documentation ](https://twelvedata.com/docs/introduction/overview)      |
| **Alpha Vantage** | Market news & sentiment, top gainers/losers, earnings call transcript, macro indicators (inflation, CPI, unemployment, fed funds, natural gas, real GDP), commodities (gold/silver) |     [Alpha Vantage API Documentation](https://www.alphavantage.co/documentation/)      |

The full endpoint list — grouped by the scoring category each feeds — is in
[`API.md`](API.md).

> **Exception:** MACD is Premium-tier on Alpha Vantage, so it is **derived
> manually in the pipeline (mart layer)** from EMA12/EMA26, never pulled from the
> indicator endpoint. Technical indicators and volatility analytics are
> computed in-Dagster from raw price bars as pure derivations, not API calls.

---
## Scoring Model

Deterministic, rule-based, weighted formula — no ML/LLM in the core score.
Weights are **provisional** (v2, backtest-informed: Valuation 62%, Trend 24%,
Sentiment 10%, Moat 4%; volatility is a separate output, not blended in). See
[`MODEL.md`](MODEL.md) for sub-scores, fair-value methodology, thresholds,
and the evidence behind each revision.

An LLM layer may be added *on top of* the deterministic score later for
narrative analysis — it will never replace or obscure the deterministic core.

---
## Cadence is heterogeneous by design

- **Near-real-time:** Finnhub quote (cache TTL ~1 min)
- **Daily:** market news (news & sentiment)
- **Weekdays:** movers, IPO/earnings calendars
- **Monthly:** commodities, macro indicators, stock symbol listing
- **Quarterly/irregular:** fundamentals, earnings, transcripts

Cadence is heterogeneous primarily to avoid hitting API rate limits specifically with Alpha Vantage, which has a very limited free tier API limit.

---

## Backtesting & Validation

The scoring layer is validated with a **point-in-time replay harness**: every
replay date re-runs the deterministic scorer with an `as_of` cutoff, so
bar-dated inputs cannot see the future, then records what actually happened
over the next 5/20/60 trading bars. Replays need ≥210 prior bars (so SMA200-based
trend components aren't degenerate) and a full forward window, or they're skipped.

**Sample:** 13 large-cap tickers × ~500 daily bars each → **431 replays**
spanning 2025-06 → 2026-05. All diagnostics bootstrap whole *replay dates*,
because 13 tickers scored on the same weekly dates are not 431 independent
observations.

### Does the score rank-order outcomes?

| Metric | Result |
| ------ | ------ |
| Spearman ρ (confidence vs 60d forward return) | **+0.24** [+0.17, +0.31], excludes 0 |
| Train window only (9 mo) | +0.33 [+0.26, +0.40] |
| Held-out window (last 2 mo) | ≈ 0 — regime-dependent, see limits |
| Volatility score vs realized forward vol | **+0.61** (validated separately from confidence) |

Realized 60d forward returns by rating (v2 weights + bands):

| Rating | n | mean 60d ret |
| ------ | - | ------------ |
| Strong Buy | 74 | +9.4% |
| Buy | 160 | **+14.1%** |
| Hold | 152 | +4.7% |
| Sell | 38 | +1.8% |
| Strong Sell | 7 | +2.4% |

The ladder is monotone where it counts: buy-rated names beat hold, and the
low bands mark genuinely below-market names.

### What the backtest changed

1. **Weights v1 → v2 (52/21/21/6 → 62/24/10/4).** Per-category attribution on
   train-window replays showed valuation was the only positively-correlated
   category (+0.38) while sentiment (−0.30) and moat (−0.25) correlated
   *negatively* — weight moved toward what carries signal.
2. **Rating bounds recalibrated (75/60/40/25 → 66/59/50/46).** The original
   bands assumed a score spread the model never produces (observed 43.7–69.1),
   so Sell/Strong Sell were unreachable. Under the new bounds the Sell bucket
   realized −2.9% mean forward return vs Hold's +5.4%.
3. **Buy-plan stops widened ×3.** Trade-level simulation (enter at advised
   price, honor stop-loss) showed the original ATR stops killed ~84% of
   positions before any target could be reached — median trade −2.4%. After
   widening: avg/trade +13.5% (train) / +16.3% (held-out), win rate 25% → 73%.

### Honest limits

- **One window, one regime.** The held-out period showed near-zero score↔return
  discrimination under *both* weightings — the edge is regime-dependent, and no
  reweighting within current category definitions fixes that.
- Bull-market sample only; no bear-market data yet.
- Overlapping observations: effective sample size is closer to ~50 independent
  weeks than 431 rows.
- Slow inputs (quarterly fundamentals, transcripts) are used as-landed rather
  than as-of-publication — free-tier sources don't expose reliable report
  timestamps; lookahead risk is small but nonzero.
- The trade simulation measures plan quality, not a tradable strategy: users
  choose their own exits.

Harness lives in `stockidence.backtest` / `backtest_metrics` /
`backtest_trades`; methodology and every constant revision are documented in
[`MODEL.md`](MODEL.md).

---
## Docs

| Doc              | What it covers                                        |
| ---------------- | ----------------------------------------------------- |
| `ARCHITECTURE.md` | Warehouse layers, watermark/staleness design, data flow diagram |
| `API.md`          | Every endpoint used, grouped by scoring category, with JSON samples |
| `MODEL.md`        | Scoring weights, sub-scores, fair-value & target-price methodology, thresholds |