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

- a **valuation reference** which contains a fair value anchor based on ...
- Technical statistics (RSI, ATR, BBANDS, SMA, EMA, ...)

Additionally the app contains other resources such as the model page, which shows the models ranking for tickers in the S&P 500 universe, and a discover page which contains useful information such as top gainers/losers, IPOs, earnings calendar, economy & commodities, and market news.

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
## Models

Ticker pages show no confidence score, advice, or buy/sell recommendation —
just a **fair value** anchor (blended DCF + own-history comparables) and raw
**technical statistics** (RSI, CCI, MACD, moving averages, …). See
[`TICKER_STATS.md`](TICKER_STATS.md) for the fair-value methodology and the
full stat list.

Alongside it, a quarterly **XGBoost `rank:ndcg` model**
orders the stocks in the S&P 500 by expected next-quarter return (ranking only, no
price prediction). The website's Model page serves it from
`mart.model_rankings`. See [`Model/README.md`](Model/README.md).

---
## Cadence is heterogeneous by design

- **Near-real-time:** Finnhub quote (cache TTL ~1 min)
- **Daily:** VIX / S&P 500 market indexes (FRED)
- **Twice daily + overnight:** market news & sentiment (7am / 7pm ET pulls, plus the 01:00 UTC daily pull; upserts on article_id, served with SQL-side date filter + paging)
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
- **Why validation starts in 2019 when data goes back to 2012.** 2019-01-01
  is the first walk-forward *test* cutoff (`CUTOFFS` in the notebook), not a
  data filter — `build_dataset.py` loads everything from 2012 on. The
  2012→2018 years are not discarded: they train every cutoff's model and
  warm up the trailing features (SMA200, 252-day vol/drawdown, 12-month
  returns all need a year-plus of history before the first test quarter).
  Starting tests earlier would grade the model on barely-trained fits.
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
## Deploy

One EC2 box runs the whole stack via Docker Compose — FastAPI, Dagster
(webserver + daemon; the push model needs both up for ticker refreshes),
and the SPA behind nginx on port 80:

```bash
cp .env.example .env   # fill in provider keys
docker compose up --build -d
```

- `t3.small` (~$15/mo) is the sweet spot; `t3.micro` risks OOM on the
  quarterly retrain. The 1.4 GB warehouse rides along as a `./data` volume
  (back it up — EBS snapshots are the simplest story).
- First boot against an empty `./data`: run a backfill
  (`Model/scripts/run_backfill.py`), then open `:80`. The Dagster UI is
  bound to localhost only — reach `:3000` over an SSH tunnel.
- EC2 security group needs only port 80 (and 22 for you). HTTPS: put the
  box behind an ALB with an ACM cert, or add certbot to the nginx service.

---
## Docs

| Doc              | What it covers                                        |
| ---------------- | ----------------------------------------------------- |
| `ARCHITECTURE.md` | Warehouse layers, watermark/staleness design, data flow diagram |
| `API.md`          | Every endpoint used, grouped by scoring category, with JSON samples |
| `TICKER_STATS.md` | Fair-value methodology and the technical statistics on ticker pages |
| `Model/README.md` | Ranking model spec, validation, quarterly refresh pipeline |