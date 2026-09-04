# Stockidence
--- 
## What this is

A **stock confidence rating pipeline**. The scoring logic is
relatively deterministic, the focus is on the data ingestion and the app
itself rather than the algorithm. The scoring layer has since been
**backtested point-in-time and recalibrated once** on that evidence (see
[Model Validation](#model-validation)).

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
  No sensors: the frontend launches the `refresh_tickers` job directly
  (`POST /api/pipeline/refresh`), and a quarterly `quarterly_model_refresh`
  job refreshes the universe, rebuilds the training dataset, and retrains
  the ranking model.
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
| **FRED**         | Market-wide daily index levels — CBOE VIX (`VIXCLS`, since 1990) and S&P 500 price index (`SP500`, ~10y daily history); read as point-in-time market-regime features by the ML model datasets, not the deterministic scorer | [FRED Series Observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) |

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
[`TICKER_STATS.md`](TICKER_STATS.md) for the fair-value methodology and the
technical statistics shown on ticker pages.

An LLM layer may be added *on top of* the deterministic score later for
narrative analysis — it will never replace or obscure the deterministic core.

Alongside the per-ticker rating, a quarterly **XGBoost `rank:ndcg` model**
orders the whole universe by expected next-quarter return (ranking only, no
price prediction). The website's Model page serves it from
`mart.model_rankings`. See [`Model/README.md`](Model/README.md).

---
## Cadence is heterogeneous by design

- **Near-real-time:** Finnhub quote (cache TTL ~1 min)
- **Daily:** market news (news & sentiment), VIX / S&P 500 market indexes (FRED)
- **Weekdays:** movers, IPO/earnings calendars
- **Monthly:** commodities, macro indicators, stock symbol listing
- **Quarterly/irregular:** fundamentals, earnings, transcripts

Cadence is heterogeneous primarily to avoid hitting API rate limits specifically with Alpha Vantage, which has a very limited free tier API limit.

---

## Model Validation

The production model is validated with **walk-forward backtesting**: every
quarter from 2019→2025, the ranker trains on all history before the quarter
cutoff and is graded on that quarter's realized returns — 26 out-of-sample
quarters, 7,661 test rows. No lookahead: features are point-in-time
snapshots, targets are forward returns.

| Metric | Result |
| ------ | ------ |
| Rank IC, pooled (predicted vs realized rank) | **+0.163** (random = 0) |
| Top-10 excess over universe mean | **+3.90 pp/qtr** (t=+1.44, positive 73% of quarters) |
| Top-25 excess over universe mean | **+5.08 pp/qtr** (t=+2.39, positive 77% of quarters) |
| Top-quintile excess | **+2.99 pp/qtr** (t=+2.22, positive 73% of quarters) |
| Precision@10 (predicted top-10 ∩ realized top-10) | **14.6%** (random 3.4%) |
| Top-20 vs S&P 500 | **+5.53 pp/qtr**, beats the index 73% of quarters |

Year-by-year top-20 vs S&P (pp/qtr, hit rate): 2019 +4.01 (75%), 2020
+15.56 (100%), 2021 −3.46 (50%), 2022 +0.81 (50%), 2023 +12.09 (100%),
2024 +2.54 (75%), 2025 +8.80 (100%).

### Honest limits

- **Quarterly grain, slow feedback.** Only ~4 fresh observations per year —
  regime shifts (e.g. 2021–2022, when the model roughly tracked the index)
  take quarters to detect, and 26 quarters is a small sample for t-stats
  near ±2.
- **Momentum/risk concentration.** The ranker leans into names with strong
  trailing momentum and drawdown profiles; top cohorts can concentrate in
  high-beta growth — it ranks, it does not manage risk.
- **Bull-market sample only** (2019→2025 window); no sustained bear market
  in the validation period.
- **Overlapping cohorts:** the same names recur across adjacent quarters, so
  effective independence is lower than 7,661 rows suggests.

Harness lives in `Model/notebooks/production_ranking_model.ipynb`
(walk-forward cells + S&P benchmark + artifact export); the model spec,
feature set, and refresh pipeline are documented in
[`Model/README.md`](Model/README.md).

---
## Docs

| Doc              | What it covers                                        |
| ---------------- | ----------------------------------------------------- |
| `ARCHITECTURE.md` | Warehouse layers, watermark/staleness design, data flow diagram |
| `API.md`          | Every endpoint used, grouped by scoring category, with JSON samples |
| `TICKER_STATS.md` | Fair-value methodology and the technical statistics on ticker pages |
| `Model/README.md` | Ranking model spec, validation, quarterly refresh pipeline |