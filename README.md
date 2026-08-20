# Stockidence — Stock Confidence Rating Pipeline

## What this is

A **stock confidence rating pipeline**. The scoring logic is a
relatively determinstic as I wanted to focus more on the data ingestion and app it self rather than the algorithm.
Though once I finish a MVP, I will revist the scoring logic and run backtests.

**The problem it answers:** *"I want to buy this stock but don't know if it's a
good time, and I don't have time to research it."* The app outputs, for any
ticker:

- a **confidence rating** + advice (`strong buy / buy / hold / sell / strong sell`)
- a **separate volatility score**
- for buy-rated tickers: an **advised buy price**, **stop-loss price**, and
  **holding-style advice** (long-term hold / swing trade / day trade)

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

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full data flow.

## Data Sources

Sources are deliberately limited to free tiers — rate limits are a problem the
caching layer exists to solve, not a problem to buy around.

| Source        | Used for                                                                  |
| ------------- | ------------------------------------------------------------------------- |
| **Finnhub**   | Company profile 2, basic & as-reported financials, EPS surprises, insider sentiment, recommendation trends, peers, IPO & earnings calendars, quote, symbol search, market status/holiday |
| **Twelve Data** | Price time series (`interval=1day`, split-adjusted); weekly/monthly are resampled downstream in the warehouse, not fetched |
| **Alpha Vantage** | Market news & sentiment, top gainers/losers, earnings call transcript, macro indicators (inflation, CPI, unemployment, fed funds, natural gas, real GDP), commodities (gold/silver) |

The full endpoint list — grouped by the scoring category each feeds — is in
[`API.md`](API.md).

> **Exception:** MACD is Premium-tier on Alpha Vantage, so it is **derived
> manually in the pipeline (mart layer)** from EMA12/EMA26, never pulled from the
> indicator endpoint. Technical indicators and volatility analytics are
> computed in-Dagster from raw price bars as pure derivations, not API calls.

## Scoring Model

Deterministic, rule-based, weighted formula — no ML/LLM in the core score.
Weights are **provisional** (Valuation 52%, Trend 21%, Sentiment 21%, Moat 6%;
volatility is a separate output, not blended in). See
[`MODEL.md`](MODEL.md) for sub-scores, fair-value methodology, and thresholds.

An LLM layer may be added *on top of* the deterministic score later for
narrative analysis — it will never replace or obscure the deterministic core.

## Cadence is heterogeneous by design

- **Near-real-time:** price/quote data (Twelve Data, Finnhub quote)
- **Daily:** persistent market data (movers, IPO/earnings calendars, news)
- **Monthly:** commodities, macro indicators
- **Quarterly/irregular:** fundamentals, earnings, transcripts

Cadence is heterogeneous primarily to avoid hitting API rate limits specifically with Alpha Vantage, which has a very limited free tier API limit.

## Docs

| Doc              | What it covers                                        |
| ---------------- | ----------------------------------------------------- |
| `ARCHITECTURE.md` | Warehouse layers, watermark/staleness design, data flow diagram |
| `API.md`          | Every endpoint used, grouped by scoring category, with JSON samples |
| `MODEL.md`        | Scoring weights, sub-scores, fair-value & target-price methodology, thresholds |