# Stockidence

**Live:** [stockidence.com](https://stockidence.com) · [GitHub](https://github.com/beavan-james/Stockidence)

---
## What this is

**A quarterly stock-ranking model, and a site built around it.** Every quarter
an XGBoost `rank:ndcg` model orders US stocks by how likely each is to beat
the rest of the list over the next three months — every stock in a ~500-name
universe with enough price and fundamentals history (328 in the Q4 2026
ranking). It ranks; it
does not predict prices.

**The question it answers:** *"I'm interested in this stock — where does the
model put it, and why?"* For any ranked stock the site shows its rank, tier
(which fifth of the list it falls in), rank within its sector, how it moved
since last quarter, and **how the model got there**: each of the model's 13
inputs, the stock's value next to the list median, and how much that input
pushed the score up or down (exact SHAP contributions that add up to the
score).

### The site

| Page | What it shows |
| ---- | ------------- |
| **Rankings** (home) | The quarter's full ranked list, a lookup that searches only ranked stocks, every stock as a tier-coloured distribution strip, the top of the list, sector tilt of the top fifth |
| **Stock page** | Rank context plus the input-by-input score breakdown and a plain-English verdict ("strong on momentum, held back by risk") |
| **Model** | Walk-forward track record vs the S&P 500 by quarter, what the model weighs most, how it works and its limits |
| **Market** | Context, not the product: daily movers, macro and commodities, news, IPO and earnings calendars |

**Dates.** A ranking is labelled by its *snapshot date* — the quarter end
whose data it uses — and is for the quarter after it: the 2026-09-30 snapshot
is the Q4 2026 ranking. Only finished quarters are ranked.

**Design.** Dark blue-black canvas, one typeface (Inter Tight) throughout, with
Instrument Serif kept for the header wordmark only. Sections are separated by
hairline rules rather than boxed cards. One brand gradient (light blue → cobalt) that doubles as the tier
scale: brighter means more favoured. No decorative motion; colour is reserved
for meaning (tiers, gains/losses).

---
## How it's built

- **Orchestration:** Dagster. Scheduled jobs land market-wide data on its own
  cadence (below); the quarterly `quarterly_model_refresh` job (03:00 UTC on
  the first day of each quarter) refreshes **every ticker in the warehouse**,
  rebuilds the training dataset, retrains the model and publishes the new
  ranking. `model_retrain` runs just the dataset rebuild + retrain, for
  re-running once the data is already fresh.
- **Incremental loads:** per-(endpoint, ticker) watermarks drive a
  staleness gate, so a refresh only calls a provider when that data has gone
  stale (a quote in a minute, prices in a day, fundamentals in months). Bulk
  refreshes resync watermarks from the stored rows first and re-pull any
  ticker whose price history has holes.
- **Guard rails:** the dataset step refuses to publish when most tickers'
  prices are stale (the current ranking stays up), skips quarters too thin
  to train on, and logs failed fetches by endpoint.
- **Warehouse:** DuckDB, three-layer schema `raw → staging → mart`. The
  ranking, per-stock contributions, input weights and track record live in
  `mart.model_*` tables written by the retrain.
- **Serving & UI:** FastAPI (`src/stockidence/api/`) exposes the mart as a
  typed REST API (`/api/rankings`, `/api/rankings/{ticker}`,
  `/api/model/overview`, market endpoints); a React + TypeScript SPA
  (`frontend-react/`) renders it and never calls providers directly.

The older per-ticker rating pipeline (`refresh_tickers` job, `/api/rating`)
is still in the backend but no longer used by the site.

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
## The model

An XGBoost `rank:ndcg` model on the quarterly grain, trained on every
finished quarter since 2012 with 13 raw point-in-time inputs: momentum
(3- and 12-month return, price vs 200-day average, distance from the 52-week
high), risk (1-year price swing, worst drawdown, average daily range) and
fundamentals from the latest filing as of the snapshot (returns on equity and
assets, free cash flow, leverage, liquidity, cash). Spec, feature set, dates
and refresh pipeline: [`Model/README.md`](Model/README.md).

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

The production model is validated with **walk-forward backtesting**: for
every quarter from 2019 to mid-2025 the ranker trains only on snapshots
before that quarter, then its picks are graded on the returns that
followed — 26 out-of-sample quarters. No lookahead: features are
point-in-time snapshots, targets are forward returns.

**Latest retrain** (Q4 2026 ranking, 2026-09-30 snapshot, 328 ranked stocks;
universe expanded to every ticker in the warehouse):

| Metric | Result |
| ------ | ------ |
| Top-20 vs S&P 500 | **+4.57 pp/qtr**, beats the index **62%** of quarters |
| Top-20 vs the whole ranked list | **+4.33 pp/qtr** |
| Out-of-sample quarters / test rows | 26 / 7,691 |

Year by year, top-20 vs S&P 500 (pp/qtr, quarters ahead): 2019 +1.54 (2/4),
2020 +12.84 (3/4), 2021 −4.35 (1/4), 2022 +1.74 (2/4), 2023 +10.74 (3/4),
2024 +2.14 (3/4), 2025 +10.20 (2/2).

**Ranking quality** (same walk-forward run, measured by the 2026-10-03
`model_retrain`):

| Metric | Result |
| ------ | ------ |
| Rank IC, pooled (predicted vs realized rank) | +0.142 (random = 0) |
| Top-10 excess over universe mean | +4.25 pp/qtr (t=+1.51, positive 62% of quarters) |
| Top-25 excess over universe mean | +4.13 pp/qtr (t=+1.91, positive 62% of quarters) |
| Top-quintile excess | +2.62 pp/qtr (t=+1.82, positive 62% of quarters) |
| Precision@10 (predicted top-10 ∩ realized top-10) | 14.6% (random 3.4%) |
| Precision@25 | 21.8% (random 8.5%) |

The numbers came down from the previous run (15,874 rows × 377 tickers;
rank IC +0.163 → +0.142, top-20 vs S&P +5.53 → +4.57 pp/qtr). The current
fit trains on 15,916 rows × 380 tickers (snapshots 2012-09-30 → 2026-06-30)
with corrected forward-return targets, so the two runs aren't strictly
comparable. None of the excess-return t-stats clear 2.

> The notebook's "beats S&P N% of quarters" line actually reports the share
> of quarters where the top 20's return was positive (69% this run); the
> hit rate against the S&P is 62%, matching `mart.model_track_record`.

**What it weighs now** (share of a typical stock's score, Q4 2026 ranking):
average daily range 25%, worst 1-year drawdown 21%, 1-year price swing 12%,
cash / assets 7%, distance from 52-week high 6%, return on assets 6%,
12-month return 5%, everything else ≤5%.

### Honest limits

- **Quarterly grain, slow feedback.** Only ~4 fresh observations per year —
  regime shifts (e.g. 2021–2022, when the model trailed or roughly tracked
  the index) take quarters to detect, and with 26 quarters none of the
  excess-return t-stats clear 2.
- **Why validation starts in 2019 when data goes back to 2012.** 2019-01-01
  is the first walk-forward *test* cutoff (`CUTOFFS` in the notebook), not a
  data filter — `build_dataset.py` loads everything from 2012 on. The
  2012→2018 years are not discarded: they train every cutoff's model and
  warm up the trailing features (SMA200, 252-day vol/drawdown, 12-month
  returns all need a year-plus of history before the first test quarter).
  Starting tests earlier would grade the model on barely-trained fits.
- **Risk-profile concentration.** In the latest retrain the three risk
  inputs (daily range, drawdown, price swing) explain ~59% of a typical
  score, so top cohorts can concentrate in volatile, high-beta names — it
  ranks, it does not manage risk.
- **2021 was a losing year** (top 20 trailed the S&P by 4.35 pp/qtr, ahead
  in 1 of 4 quarters): the model can lag for several quarters at a time.
- **Mostly a bull-market sample** (2019→2025 window); the 2022 drawdown is
  the only sustained bear market in the validation period.
- **Overlapping cohorts:** the same names recur across adjacent quarters, so
  effective independence is lower than 7,691 rows suggests.

Harness lives in `Model/notebooks/production_ranking_model.ipynb`
(walk-forward cells + S&P benchmark + artifact export); the model spec,
feature set, and refresh pipeline are documented in
[`Model/README.md`](Model/README.md).

---
## Deploy

One always-free Oracle Ampere box (2 OCPU / 12 GB) runs the whole stack via
Docker Compose — FastAPI, Dagster (webserver + daemon) and the SPA behind
nginx (HTTPS on 443, port 80 redirects):

```bash
cp .env.example .env   # fill in provider keys
docker compose up --build -d
```

- The 1.4 GB warehouse rides along as a `./data` volume (back it up — a
  boot-volume backup policy is the simplest story).
- First boot against an empty `./data`: copy the warehouse up (don't
  re-backfill through rate-limited APIs) or run a backfill
  (`Model/scripts/run_backfill.py`), then open `:80`. The Dagster UI is
  bound to localhost only — reach `:3000` over an SSH tunnel.
- Firewall needs only port 80 (and 443 once HTTPS is on, plus 22 for you).
  HTTPS: certbot on the box against your domain (Route 53 A record →
  reserved public IP).

### Auto-deploy (cron pull)

Push-to-deploy over SSH is intentionally unsupported: port 22 allows one
admin IP only, and Actions runners egress from unallowlistable Azure ranges.
Instead the box polls itself — `scripts/auto-deploy.sh` on a 5-minute cron
fast-forwards to `origin/master` and rebuilds + health-checks only when the
commit moved (lock-guarded, logs to `auto-deploy.log`):

```bash
(crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/Stockidence/scripts/auto-deploy.sh >> $HOME/Stockidence/auto-deploy.log 2>&1") | crontab -
```

`./data` and `.env` are untracked so deploys can't clobber the warehouse or
keys. (If push deploys are ever wanted back, the path is a Tailscale tailnet
so runners get a private route to the box — not opening SSH to the world.)

---
## Docs

| Doc              | What it covers                                        |
| ---------------- | ----------------------------------------------------- |
| `ARCHITECTURE.md` | Warehouse layers, watermark/staleness design, data flow diagram |
| `API.md`          | Every endpoint used, grouped by scoring category, with JSON samples |
| `TICKER_STATS.md` | Fair-value methodology of the older per-ticker rating pipeline (no longer shown on the site) |
| `Model/README.md` | Ranking model spec, validation, quarterly refresh pipeline |

---
## Local development

```bash
uv run uvicorn stockidence.api.app:app --reload   # API on :8000
uv run dagster dev                                # Dagster UI on :3000
cd frontend-react && npm install && npm run dev   # site on :5173 (proxies /api)
```