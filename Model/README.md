# Notes about Model Fitting

## Dataset Ticker List

**Universe: 123 tickers**, 2011-08 → 2026-07, ~21.3k month-rows:

```
AAPL ABBV ADBE ADP AIG ALL AMBP AMD AMGN AMT AMZN ANET APP AVGO AXP BAC BE BKR BMY BRK.B BX C CAT CI CME COP
COST CRM CSCO CTAS CVS CVX DE DHR DIS DKNG DUK EBAY ELV EMR EOG ETN FCX FDX FI GD GE GILD GOOGL GS HAL HD HLT
HON IBM INTC INTU ISRG ITW JNJ JPM KDP KMB KMI KO LIN LLY LMT LOW MA MAR MCD MDLZ MDT MET META MPC MRK MS
MSFT MU NBIS NEE NKE NOC NOW NVDA ORCL OXY PANW PFE PG PLD PLTR PNC PRU PSX QCOM RSG RTX SBUX SCHW SHW SLB
TGT TJX TMO TMUS TRV TXN UNH UNP UPS USB V VLO VRTX WM WMB WMT XOM YUM ZTS
```

## Goals

- Target Value is to predict next month return for each ticker i.e. given data through month N, predict the return for month N+1.

- Train: All tickers, all months up to cutoff (Jan. 2024)

- Test: All tickers, all months after cutoff (Jan. 2024)

- Models: Ridge Regression (L2 penalty) and Gradient Boosted Trees (separate models, ridge regression is the secondary model and can be used for feature inference)

## Roadblocks

- First roadblock encountered when trying initial training with just data from 20 tickers. Simply not enough data leading to the modeling not being able to find any real signal. All weights were near zero and model was prediciting hold/near 0.0 gain for every ticker. (Since I removed the Alpha Vantage news & sentiment api there is less rate limiting so will work to significantly increase the dataset size and then re-run training.)

- Another thing to note is that the training issues could also be due to the fact that the model is trying to predict next month returns which is more susceptible to outside noise as supposed to the more common predicting next day returns. (Will test a weekly and quarterly model to see if this amends the issue at all.)

- Noticing some improvements after switching to a quarterly model and increasing the dataset size to 120 tickers. Will continue to increase dataset size to around 500 tickers and then re-run training. Seems like between various models (XGBoost, Ridge Regression, etc.) XGBoost is performing the best and holds a higher rank IC however directional accuracy is sitting at/below the market baseline so clearly needs more work. Will continue to experiment with various features and models.

## Dataset

**Dataset**: Model/train_dataset.parquet — 4136 rows × 33 columns, 27 tickers, 2011-2026
**Feature columns**: sma_20, sma_50, sma_200, ema_12, ema_26, rsi_14, adx_14, atr_14, macd_hist, stoch_k_14, stoch_d_14, cci_20, stddev_252, max_drawdown_252, roe, roa, debt_equity, current_ratio, cash_to_assets, fcf, plus derived: price_to_sma20/50/200, atr_pct, fcf_yield
**Target**: target_return (next-month close-to-close return)

`tentative` **Walk-forward plan**: expanding window, first cutoff Jan 2024`

`features` - Notice the feature list does not include any news or sentiment features. This is due to not being able to pull news and sentiment data more than 1 year back. To avoid having a sparse dataset, the model only uses technical features. The plan is to either add news and sentiment weighting to the model down the road or create a separate model for news and sentiment features.

Feature additions: sector/industry, VIX index, S&P 500 index, Russel 2000 index, 

## Measures

1. Rank IC (primary) — within each test month, Spearman correlation of predicted vs actual. Tests ordering, which is exactly what "should I buy this vs that" needs, and is immune to the noise problem.
2. Directional accuracy — % of months sign matches. Baseline is 58.9% (returns were positive 58.9% of the time — "always predict up" scores that). Below ~59% = no edge.
3. MSE/RMSE vs baselines — predict 0, predict last month's return, predict universe mean.
4. Quintile spread (maps to your product) — sort predicted returns into quintiles each month, average realized return per quintile, check Q5−Q1 is positive and monotonic. This is the honest version of "was the model right": does the top-of-the-ranking actually outperform the bottom?
5. In terms of a direct "percent correct number", model predictions can be classified into buckets i.e. strong buy >= 10% gain, etc. and then compare to actual return buckets.