# Production Ranking Model

The website's screener is an **XGBoost `rank:ndcg` model** on the **quarterly**
grain. It does not predict returns, it **orders tickers within each quarter's
cohort** so the top of the list beats the bottom. Ranking (not regression)
because the signal proved strongest at the head of the list: top-ranked names
outperform while pooled return accuracy stays noisy.

## Model spec

- **Objective**: `rank:ndcg` — optimizes the head of the ranking
  (top-10 / top-25 / top quintile), which is what the screener needs
- **Grain**: quarterly; target is next-quarter return
- **Features (core-13, raw PIT columns, no engineering)**: price_to_sma200,
  stddev_252, max_drawdown_252, atr_pct, return_3m, return_12m,
  distance_from_52wk_high, roe, roa, debt_equity, current_ratio,
  cash_to_assets, fcf_to_assets (+ sector as display label, not a booster input)
- **Hyperparameters**: 150 rounds, max_depth 3, eta 0.05, subsample 0.8,
  colsample_bytree 0.8, reg_alpha 0.1, reg_lambda 1.0, seed 42
- **Excluded tickers**: AMBP, BE, BRK.B, CRM, FI, NBIS (sparse/unusable history)
- **A/B note**: a 40-feature engineered variant (vol-scaled momentum,
  cross-sectional ranks, market-relative momentum) *halved* pooled IC and
  top-10 excess — dropped in favor of the raw core-13 set

## Training data

- Built by `Model/scripts/build_dataset.py` (`--freq quarterly`,
  optional `--tickers` / `--tickers-file Model/training_universe.txt`;
  no flag = every ticker in the warehouse)
- Latest scored snapshot: **2026-09-30, 328 tickers** (the Q4 2026
  ranking; top: DKNG, FISV, ORCL, RDDT, PSKY). First run on the full
  warehouse universe.
- Current fit (2026-10-03 retrain): **15,916 rows × 380 tickers**,
  snapshots 2012-09-30 → 2026-06-30 (outcomes through 2026-09-30)
- No news/sentiment features — history only goes back ~1 year, which would
  sparsify the dataset. Technicals + fundamentals only.

## Validation (walk-forward, 26 quarters 2019→2025)

Latest retrain (7,691 test rows), from `mart.model_track_record`:

- Top-20 vs S&P 500: **+4.57 pp/qtr**, beating the index 62% of quarters
- Top-20 vs the whole ranked list: **+4.33 pp/qtr**
- Input weights (share of a typical score): average daily range 25%, worst
  drawdown 21%, price swing 12%, cash / assets 7%, rest ≤6%

Ranking quality, same run (measured by the 2026-10-03 `model_retrain`):

- Rank IC (pooled): +0.142
- Top-10 excess: +4.25 pp/qtr (t=+1.51, positive 62% of quarters)
- Top-25 excess: +4.13 pp/qtr (t=+1.91, positive 62% of quarters)
- Top-quintile excess: +2.62 pp/qtr (t=+1.82, positive 62% of quarters)
- Precision@10: 14.6% (random 3.4%) · Precision@25: 21.8% (random 8.5%)

Previous run (15,874 rows × 377 tickers, 7,661 test rows) for comparison: rank IC
+0.163, top-20 vs S&P +5.53 pp/qtr. Note the notebook's "beats S&P N%" line
reports quarters with a positive top-20 return (69%), not the S&P hit rate
(62%); `mart.model_track_record` has the correct figure.

## Refresh pipeline (quarterly DAG)

`quarterly_model_refresh` in `src/stockidence/definitions.py`, cron
`0 3 1 1,4,7,10 *`:

1. **Refresh universe** — incremental re-ingest of every ticker in the warehouse (watermarks
   intact; failed fetches retried 3× then recorded and skipped)
2. **Rebuild dataset** — `build_dataset(freq="quarterly")` →
   `Model/datasets/train_dataset_quarterly.parquet` (quarters whose forward
   quarter has closed) + `score_dataset_quarterly.parquet` (the newest
   quarter, forward return not yet known)
3. **Retrain** — re-executes `Model/notebooks/production_ranking_model.ipynb`,
   which refits on all history, overwrites
   `Model/artifacts/ranking_ndcg.{json,meta.json}`, scores the newest
   quarter, and exports that ranked cohort to **`mart.model_rankings`** +
   `latest_rankings.json` (the API serves the latest `as_of`)

Re-running only steps 2–3 (data already fresh, e.g. after a notebook failure):
launch the **`model_retrain`** job, which skips the hours-long refresh.

The retrain also exports, for the newest cohort, each stock's model inputs and
per-input SHAP contributions (`mart.model_contributions`; they sum exactly to
the score), cohort-wide input weights (`mart.model_feature_importance`) and the
walk-forward track record (`mart.model_track_record`).

**Dates.** Every published date is a snapshot date: the quarter end whose
data was used. A ranking `as_of` 2026-09-30 is built from data to Sep 30 and
ranks stocks for Q4 2026; the model behind it learned from every earlier
snapshot whose following quarter has finished (the last is 2026-06-30, whose
outcome is the Jul–Sep return, so outcomes run through Sep 30). Only finished
quarters are scored. Internally the dataset still labels rows by quarter
start (2026-07-01 = the 2026-09-30 snapshot); exports convert.

## Serving

- `GET /api/rankings` → `{as_of, universe_size, items: [{rank, ticker,
  sector, score}]}` from `mart.model_rankings`
- `GET /api/rankings/{ticker}` → rank, tier, sector rank, previous-quarter
  rank and the per-input score breakdown (stock page)
- `GET /api/model/overview` → input weights + track record (Model page)
- Scores are ordinal within-quarter ranks, not expected returns; the site
  shows rank, percentile and quintile tier instead of raw scores

## Stocks of the Week (weekly model)

The website's **Weekly** page is a second ranker from the same family,
re-run every Friday after the US close. It orders the cohort by how likely
each stock is to beat the rest of the list **next week**: bought at
Monday's open, sold at Friday's close. Code lives in
`src/stockidence/weekly.py` (a module, not a notebook).

### Spec

- **Objective, hyperparameters, inputs**: same as the quarterly model
  (`rank:ndcg`, core-13, 150 rounds, depth 3, eta 0.05, seed 42); each
  week's cohort is one query group graded into return quintiles
- **Grain**: weekly. A row is a Friday-close snapshot (Thursday's close on a
  holiday Friday); the weekly bars are resampled from Twelve Data daily bars
- **Target**: next-week return, Monday open → Friday close
  (`target_return`). Picked over next-quarter return by the comparison
  below
- **Excluded tickers**: the quarterly list plus VOO, which is the S&P 500
  benchmark (bought at the same Monday open, never ranked)

### Target comparison

The same 398 weekly cohorts (snapshots 2019-01-04 → 2026-08-21), ranked
four ways and graded on both horizons by
`Model/scripts/compare_weekly_targets.py`, which calls the job's own
functions:

| Target | Inputs | Top 10 vs list, next week | t | vs S&P, next week | Top 10 vs list, next 13 weeks | t |
|---|---|---|---|---|---|---|
| **Next week** | core-13 | **+67 bp** | 2.79 | +71 bp | **+9.3 pp** | 3.01 |
| Next quarter | core-13 | +50 bp | 2.44 | +53 bp | +6.8 pp | 2.28 |
| Next week | core-13 + short-term | +67 bp | 3.05 | +71 bp | +8.2 pp | 2.57 |
| Next quarter | core-13 + short-term | +61 bp | 2.85 | +64 bp | +8.7 pp | 2.77 |

Short-term inputs (13): 1- and 4-week return, RSI 14, price vs SMA 20/50,
stochastic %K, CCI 20, ADX 14, MACD histogram / price, Bollinger %b, volume
vs its 13-week average, weekly range, short/long volatility ratio. 13-week
outcomes overlap week to week, so their t-stats use every 13th week.

Shipped: **next week, core-13**. It leads on both horizons (the model
trained on next-week returns even beats the quarter-trained one on 13-week
returns), and the short-term inputs add 13 columns without raising the
average lead.

### Validation

Walk-forward: a refit every quarter on the weeks whose outcome had closed
by that quarter's first Monday, scoring the next 13 weekly cohorts, so no
week is scored by a model that saw it. The live job refits every week.

Development run on a copy of the local warehouse (prices to 2026-08-28;
398 test weeks, 125,791 test rows). Each production run writes its own
numbers to `mart.weekly_validation`, and the Weekly page shows those:

- Top 10 vs the whole list: **+67 bp/week** (t=+2.79, ahead in 58% of weeks)
- Top 10 vs S&P 500 (VOO): **+71 bp/week**, ahead in 57% of weeks
- Rank IC: +0.026 (the edge sits at the head of the list, not across it)
- Precision@10: 15.4% (random 3.2%)
- By snapshot year, top 10 vs list (bp/week): 2019 +109, 2020 +43,
  2021 +18, 2022 −62, 2023 +206, 2024 +48, 2025 +115, 2026 to Aug 21 +60
- Fit: 223,623 rows × 405 tickers, snapshots 2012-08-10 → 2026-08-21

### Refresh pipeline (Friday DAG)

`weekly_model_refresh` in `src/stockidence/definitions.py`, scheduled
`30 17 * * 5` America/New_York (Friday 5:30 pm ET):

1. **Refresh universe**: every ticker in the warehouse plus VOO, the same
   incremental runner as the quarterly job, except daily prices skip the
   staleness gate (a 1-day TTL would keep a ticker viewed during Friday's
   session from landing Friday's close). About 500 Twelve Data calls of the
   800/day free tier
2. **Rebuild dataset**: `build_dataset(freq="weekly")` →
   `Model/datasets/train_dataset_weekly.parquet` (weeks whose next week has
   closed) + `score_dataset_weekly.parquet` (this week's snapshot). The
   clock decides which week has closed (Friday 4 pm ET), so a mid-week
   manual run scores the previous week. Only tickers that landed the
   week's last close are scored; if that's under half the usual cohort the
   step fails and the current list stays up
3. **Train and rank**: walk-forward backtest, refit on every closed week,
   rank this week's snapshot, export, then grade last week's list on the
   week that just closed

`weekly_rank` runs steps 2–3 only (data already fresh).

Tables (all `mart`): `weekly_rankings` (one ranked list per `as_of`, with
each stock's `realized_return` once its week closes), `weekly_track_record`
(per week: top-10, whole-list and VOO returns; `source` = `backtest` or
`live`) and `weekly_validation` (one row of walk-forward metrics per run).

**Dates.** `as_of` is the Friday whose close the snapshot uses; the list
is for the following Monday–Friday and is graded by the next Friday's run.
Internally weekly rows are labelled by their Monday.

### Serving

- `GET /api/weekly` → this week's list with each stock's previous rank,
  last week's top 10 with realized returns, the backtest track and the
  latest validation row

### Caveats

- **No trading costs.** The backtest buys at Monday's open and sells at
  Friday's close, so it never holds over a weekend. The top 10 replaces
  27% of its names in an average week
- **Survivorship.** The universe is the tickers in the warehouse today, so
  stocks delisted since 2019 are missing. That flatters absolute returns,
  likely most for the volatile names this model favours. Compounding the
  weekly top 10 gives 55%/yr against 17% for VOO over the same weeks:
  treat that as an upper bound, not an expectation
- **Concentration.** Technology fills 38% of top-10 slots against 16% of
  the cohort; one sector holds 5 or more of the 10 in a third of weeks
- `stddev_252` (shared with the quarterly model) is the standard deviation
  of the close in dollars, so it partly measures share-price level

## Parked

- Ridge regression second model — undecided (implement or scrap); the
  ticker page fair-value/stats revamp waits on that call
