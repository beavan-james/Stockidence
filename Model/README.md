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
- **Query groups**: one per quarter's cohort, graded into return quintiles;
  rows are sorted by date before `set_group`, which reads consecutive row
  counts
- **Hyperparameters**: 150 rounds, max_depth 3, eta 0.05, subsample 0.8,
  colsample_bytree 0.8, reg_alpha 0.1, reg_lambda 1.0, seed 42
- **Excluded tickers**: AMBP, BE, BRK.B, CRM, FI, NBIS (sparse/unusable history)
- **Universe (point in time)**: a stock counts in training and in the
  walk-forward only for the snapshots it was in the S&P 500 (`in_index`), so
  a stock that joined the index after a run-up doesn't bring the run-up with
  it. The live ranking holds today's members plus stocks never in the index
  that users looked up; former members and a renamed company's old ticker
  (MMC beside MRSH) are left out (`sp500_status`). Until the membership list
  has landed, every row counts
- **A/B note**: a 40-feature engineered variant (vol-scaled momentum,
  cross-sectional ranks, market-relative momentum) *halved* pooled IC and
  top-10 excess — dropped in favor of the raw core-13 set

## Training data

- Built by `Model/scripts/build_dataset.py` (`--freq quarterly`,
  optional `--tickers` / `--tickers-file Model/training_universe.txt`;
  no flag = every ticker in the warehouse)
- Each row carries `in_index` (the company was in the S&P 500 on the
  snapshot day) and `sp500_status` (where the ticker stands on today's list:
  `current`, `former`, `never`, or `duplicate` when another warehouse ticker
  stands for the same company), read from `staging.stg_sp500_membership`
  (fja05680/sp500, fetched monthly, renames resolved to today's ticker)
- Latest scored snapshot: **2026-09-30, 328 tickers** (the Q4 2026
  ranking; top: DKNG, FISV, ORCL, RDDT, PSKY). First run on the full
  warehouse universe.
- Current fit (2026-10-03 retrain): **15,916 rows × 380 tickers**,
  snapshots 2012-09-30 → 2026-06-30 (outcomes through 2026-09-30)
- No news/sentiment features — history only goes back ~1 year, which would
  sparsify the dataset. Technicals + fundamentals only.

## Validation (walk-forward, 26 quarters 2019→2025)

Latest walk-forward (2026-11-01, with the query-group fix; local warehouse
copy, 15,569 rows × 377 tickers, 7,661 test rows):

- Top-20 vs S&P 500: **+4.77 pp/qtr** (t=+2.19), beating the index 73% of quarters
- Top-20 vs the whole ranked list: **+4.47 pp/qtr**
- Rank IC (pooled): +0.130
- Top-10 excess: +5.09 pp/qtr (t=+1.63, positive 69% of quarters)
- Top-25 excess: +4.55 pp/qtr (t=+2.34, positive 77% of quarters)
- Top-quintile excess: +3.12 pp/qtr (t=+2.30, positive 69% of quarters)
- Precision@10: 18.5% (random 3.4%) · Precision@25: 22.3% (random 8.5%)

These numbers predate the point-in-time filter below; the next retrain
writes new ones to `mart.model_validation`.

Before the fix, `set_group` got ticker-ordered rows, so each query group was
a block of mostly one ticker's history instead of a quarter's cohort. Same
data, before → after: rank IC +0.144 → +0.130, top-10 excess +6.49 → +5.09,
top-20 vs S&P +5.65 → +4.77 pp/qtr. Over 8 seeds the fix averages about
−1.2 pp/qtr on top-10 excess (paired t=−1.4, not significant), −0.3 pp/qtr
against the S&P and no change on the top quintile. Per-date IC barely moved
(+0.071 → +0.065); the pooled-IC drop is the old groups rewarding
cross-quarter ordering.

### Point-in-time S&P 500 filter (2026-11-26)

The same walk-forward on datasets rebuilt by `build_dataset.py` from the
local warehouse copy (prices to 2026-08-28). Before: every warehouse row.
After: only rows whose company was in the S&P 500 at the snapshot.

| | Before | After |
|---|---|---|
| Training rows × tickers | 16,738 × 406 | 13,807 × 380 |
| Median quarterly cohort | 316 | 279 |
| Top-20 vs S&P 500 | +4.02 pp/qtr (t=1.83) | +2.27 pp/qtr (t=1.25) |
| Top-20 vs the whole list | +3.67 (t=1.67) | +2.77 (t=1.56) |
| Top-10 vs the whole list | +4.44 (t=1.40) | +3.98 (t=1.55) |
| Whole list vs S&P 500 | +0.35 | −0.49 |
| Top-20 vs stocks of similar volatility | +1.05 (t=0.78) | +1.08 (t=1.33) |
| Rank IC (pooled) | +0.151 | +0.154 |
| No model: the 20 most volatile (atr_pct) vs the list | +6.27 | +3.43 |

Most of the drop is in the list, not in the model's ordering. Once a stock
only counts from the day it joined (TSLA from Q4 2020, PLTR from Q3 2024),
the equal-weight list goes from 0.35 pp/qtr ahead of the S&P to 0.49
behind, and picking the most volatile stocks loses half its lead. Against
stocks of similar volatility the model stays about +1 pp/qtr ahead, still
short of significance. The after column is still an upper bound: the
warehouse holds 12 former members, 93 more that still trade are planned for
a backfill, and about 180 no longer trade and can't be fetched on the free
tiers.

Live model (2026-10-03 retrain, before the fix), from `mart.model_track_record`:
top-20 vs S&P +4.57 pp/qtr (ahead 62% of quarters), rank IC +0.142, 7,691 test
rows; input weights (share of a typical score): average daily range 25%,
worst drawdown 21%, price swing 12%, cash / assets 7%, rest ≤6%. The next
quarterly retrain replaces it.

## Refresh pipeline (quarterly DAG)

`quarterly_model_refresh` in `src/stockidence/definitions.py`, cron
`0 3 1 1,4,7,10 *`:

1. **Refresh universe** — incremental re-ingest of every ticker in the warehouse (watermarks
   intact; failed fetches retried 3× then recorded and skipped)
2. **Rebuild dataset** — restages the filings and the S&P 500 membership
   list, then `build_dataset(freq="quarterly")` →
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
- **Universe (point in time)**: as the quarterly model. A week trains and
  tests only on stocks in the S&P 500 at that snapshot, and the live list
  holds today's members plus stocks never in the index

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
numbers to `mart.weekly_validation`, and the Weekly method page shows those:

- Top 10 vs the whole list: **+67 bp/week** (t=+2.79, ahead in 58% of weeks)
- Top 10 vs S&P 500 (VOO): **+71 bp/week**, ahead in 57% of weeks
- Rank IC: +0.026 (the edge sits at the head of the list, not across it)
- Precision@10: 15.4% (random 3.2%)
- By snapshot year, top 10 vs list (bp/week): 2019 +109, 2020 +43,
  2021 +18, 2022 −62, 2023 +206, 2024 +48, 2025 +115, 2026 to Aug 21 +60
- Fit: 223,623 rows × 405 tickers, snapshots 2012-08-10 → 2026-08-21

These predate the point-in-time S&P 500 filter. The same walk-forward on
datasets rebuilt from the same warehouse copy, before (every row) and
after (rows in the index at the snapshot):

| | Before | After |
|---|---|---|
| Fit rows × tickers | 223,866 × 405 | 185,095 × 382 |
| Test rows | 126,034 | 111,918 |
| Top 10 vs the whole list | +67 bp/week (t=2.79, 58%) | +28 bp/week (t=1.59, 55%) |
| Top 10 vs S&P 500 (VOO) | +70 bp/week (57%) | +25 bp/week (54%) |
| Rank IC | +0.026 | +0.019 |
| Precision@10 (random) | 15.4% (3.2%) | 12.2% (3.6%) |

The weekly edge loses more than half its size and is no longer
significant. It is still an upper bound for the reasons in the quarterly
section: 93 former members that still trade are planned for a backfill,
and about 180 can't be fetched.

### Refresh pipeline (Friday DAG)

`weekly_model_refresh` in `src/stockidence/definitions.py`, scheduled
`30 17 * * 5` America/New_York (Friday 5:30 pm ET):

1. **Refresh universe**: every ticker in the warehouse plus VOO, the same
   incremental runner as the quarterly job, except daily prices skip the
   staleness gate (a 1-day TTL would keep a ticker viewed during Friday's
   session from landing Friday's close). About 500 Twelve Data calls of the
   800/day free tier
2. **Rebuild dataset**: restages the filings and the S&P 500 membership
   list, then `build_dataset(freq="weekly")` →
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
`live`), `weekly_validation` (one row of walk-forward metrics per run) and
`weekly_feature_importance` (per list and input: mean |SHAP contribution|
across the ranked stocks, measured as in the quarterly model).

**Dates.** `as_of` is the Friday whose close the snapshot uses; the list
is for the following Monday–Friday and is graded by the next Friday's run.
Internally weekly rows are labelled by their Monday.

### Serving

- `GET /api/weekly` → this week's list with each stock's previous rank and
  each input's share of the score, last week's top 10 with realized
  returns, the backtest track and the latest validation row

### Caveats

- **No trading costs.** The backtest buys at Monday's open and sells at
  Friday's close, so it never holds over a weekend. The top 10 replaces
  27% of its names in an average week
- **Survivorship.** Rows count only while the stock was in the S&P 500,
  so a stock no longer gets credit for the run-up that put it in the index.
  Stocks that left the index are still mostly missing (delisted ones can't
  be fetched on the free tiers), which flatters absolute returns, likely
  most for the volatile names this model favours. Compounding the weekly
  top 10 gave 55%/yr against 17% for VOO before the filter: treat any such
  figure as an upper bound, not an expectation
- **Concentration.** Technology fills 38% of top-10 slots against 16% of
  the cohort; one sector holds 5 or more of the 10 in a third of weeks
- `stddev_252` (shared with the quarterly model) is the standard deviation
  of the close in dollars, so it partly measures share-price level

## Parked

- Ridge regression second model — undecided (implement or scrap); the
  ticker page fair-value/stats revamp waits on that call
