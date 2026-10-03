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

## Parked

- Ridge regression second model — undecided (implement or scrap); the
  ticker page fair-value/stats revamp waits on that call
