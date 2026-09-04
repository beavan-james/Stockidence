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
- Production fit: **15,874 rows × 377 tickers, 2012-07 → 2026-04**
- Latest scored cohort: **2026-04-01, 305 tickers** (top: MRNA 1.0055)
- No news/sentiment features — history only goes back ~1 year, which would
  sparsify the dataset. Technicals + fundamentals only.

## Validation (walk-forward, 26 quarters 2019→2025, 357-ticker universe)

- Rank IC (pooled): **+0.175**
- Top-10 excess: **+3.13 pp/qtr** (t=1.19) · Top-25: **+4.56** (t=2.26) ·
  Top-quintile: **+2.68** (t=2.24)
- Precision@10: **11.5%** (random 3.6%)
- Top-20 vs S&P 500: **+5.51 pp/qtr**, beating the index 73% of quarters

## Refresh pipeline (quarterly DAG)

`quarterly_model_refresh` in `src/stockidence/definitions.py`, cron
`0 3 1 1,4,7,10 *`:

1. **Refresh universe** — incremental re-ingest of all tickers (watermarks
   intact; failed fetches retried 3× then recorded and skipped)
2. **Rebuild dataset** — `build_dataset(freq="quarterly")` →
   `Model/datasets/train_dataset_quarterly.parquet`
3. **Retrain** — re-executes `Model/notebooks/production_ranking_model.ipynb`,
   which refits on all history, overwrites
   `Model/artifacts/ranking_ndcg.{json,meta.json}`, and exports the full
   ranked cohort to **`mart.model_rankings`** + `latest_rankings.json`

## Serving

- `GET /api/rankings` → `{as_of, universe_size, items: [{rank, ticker,
  sector, score}]}` from `mart.model_rankings`
- Website Model page renders the table (searchable, 20/page); scores are
  ordinal within-quarter ranks, not expected returns

## Parked

- Ridge regression second model — undecided (implement or scrap); the
  ticker page fair-value/stats revamp waits on that call
