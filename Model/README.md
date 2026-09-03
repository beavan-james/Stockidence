# Notes about Model Fitting

## Key Notes

The model is not a steady alpha generator. It is a **ranking model** and although it performs well it does carry momentum/risk issues.

Key turning point was noticing that the model was predicting strong buy tickers correctly with some degree of success though not necessarily predicting the entire universe of tickers correctly. This was a good sign that the model was able to find some signal and would perform better when only looking at its top-ranked tickers. This is the main reason for the model being a ranking model rather than a regression model.

## Building the training dataset

`build_dataset.py` now restricts every load to a **curated training universe**,
independent of the full ingestion universe (the warehouse may hold the whole
S&P 500 for on-demand scoring while the model trains on a smaller, cleaner set):

```
python Model/scripts/build_dataset.py --freq quarterly --tickers AAPL,MSFT,NVDA
python Model/scripts/build_dataset.py --freq quarterly --tickers-file Model/training_universe.txt
```

Set `TRAIN_TICKERS` at the top of the file for a default; no flag = every ticker
in the warehouse. This is a training-time filter — the ingest/mart layers stay
broad so the production scorer can rank any ticker against its date cohort.

## Dataset Ticker List

**Universe: 520 tickers**, 2011-08 → 2026-07, 1,841,414+ rows at daily grain

```
AAPL ABBV ABNB ADBE ADM ADP AEP AIAI AIG ALL AMAT AMBP AMD AMGN AMT AMZN ANET APD APP ASML
AVGO AXP BAC BBY BE BKR BMY BRK-B BX C CAT CB CI CMCSA CME CMG COP COST CRM CSCO
CTAS CVS CVX CZR D DAL DE DHI DHR DIS DKNG DOW DUK DVN EBAY ECL ELV EMR EOG EQIX
ERIC ETN EXC FCX FDX FI GD GE GILD GM GOOGL GPN GS HAL HD HLT HON HUM IBM INTC
INTU ISRG ITW JNJ JPM KDP KLAC KMB KMI KO LEN LIN LLY LMT LOW LRCX MA MAR MCD MCO
MDLZ MDT MET META MLM MO MPC MRK MS MSFT MU NBIS NEE NEM NFLX NKE NOC NOW NUE NVDA
O ORCL OXY PANW PEP PFE PG PLD PLTR PM PNC PPG PRU PSA PSX PYPL QCOM RSG RTX RY
SBUX SCHW SHOP SHW SLB SO SPG SQ SRE T TD TGT TJX TMO TMUS TRV TSLA TXN UAL UBER
UNH UNP UPS USB V VALE VLO VMC VRTX VZ WELL WM WMB WMT XEL XOM YUM ZTS
MCK CAH LUV F CRWD FTNT SNOW LULU STZ DEO A ACGL ADI AJG ALB AON AVB AZO 
BDX BIIB BK BKNG BLK BSX BURL CARR CBOE CCI CCL CDNS CF CHD CL CLX CMI CNC CNI COF 
CP CSX CTVA DDOG DLR DPZ DRI DXCM ED EQR EQT EW EXPE FAST GIS GWW HAS HCA HIG HPE 
HPQ HSY ICE IQV JCI KHC KR MCHP MMC MNST MPWR MRNA MTD NCLH NET NSC NTAP ODFL OKE 
ON ORLY OTIS PCAR PEG PH RCL REGN RJF ROST SNPS SPGI STLD STT SYK SYY TDG TEAM TECH 
TRGP TROW TSCO TT ULTA VICI WAT WDC WDAY WEC WSM ZS
ABT, ACN, "ADSK", "AEE", "AES", "AFL", "AIZ", "AKAM", "ALGN", "ALLE",
"AMCR", "AME", "AMP", "AOS", "APA", "APH", "APO", "APTV", "ARE", "ARES",
"ATO", "AVY", "AWK", "AXON", "BA", "BALL", "BAX", "BEN", "BF-B", "BG",
"BLDR", "BR", "BRO", "BXP", "CAG", "CBRE", "CDW", "CEG", "CFG", "CHRW",
"CHTR", "CIEN", "CINF", "CMS", "CNP", "COIN", "COO", "COR", "CPAY", "CPB",
"CPRT", "CPT", "CRH", "CRL", "CSGP", "CTRA", "CTSH", "CVNA", "DD", "DECK",
"DELL", "DG", "DGX", "DLTR", "DOC", "DOV", "DTE", "DVA", "EA", "EFX",
"EG", "EL", "EME", "EPAM", "ERIE", "ES", "ESS", "ETR", "EVRG", "EXE",
"EXPD", "EXR", "FANG", "FDS", "FE", "FFIV", "FICO", "FIS", "FISV", "FITB",
"FIX", "FOX", "FOXA", "FRT", "FSLR", "FTV", "GEHC", "GEN", "GEV", "GL",
"GLW", "GNRC", "GOOG", "GPC", "GRMN", "HBAN", "HII", "HOOD", "HRL",
"HST", "HUBB", "HWM", "IBKR", "IDXX", "IEX", "IFF", "INCY", "INVH", "IP",
"IR", "IRM", "IT", "IVZ", "J", "JBHT", "JBL", "JKHY", "KEY", "KEYS",
"KIM", "KKR", "KVUE", "L", "LDOS", "LH", "LHX", "LII", "LNT", "LVS",
"LW", "LYB", "LYV", "MAA", "MAS", "MGM", "MKC", "MMM", "MOH", "MOS",
"MRSH", "MSCI", "MSI", "MTB", "MTCH", "NDAQ", "NDSN", "NI", "NRG",
"NTRS", "NVR", "NWS", "NWSA", "NXPI", "OMC", "PAYC", "PAYX", "PCG", "PFG",
"PGR", "PHM", "PKG", "PNR", "PNW", "PODD", "POOL", "PPL", "PSKY", "PTC",
"PWR", "Q", "RDDT", "REG", "RF", "RL", "RMD", "ROK", "ROL", "ROP",
"RVTY", "SBAC", "SJM", "SMCI", "SNA", "SNDK", "SOLV", "STE", "STX", "SW",
"SWK", "SWKS", "SYF", "TAP", "TDY", "TEL", "TER", "TFC", "TKO", "TPL",
"TPR", "TRMB", "TSN", "TTD", "TTWO", "TXT", "TYL", "UDR", "UHS", "URI",
"VLTO", "VRSK", "VRSN", "VST", "VTR", "VTRS", "WAB", "WBD", "WRB", "WST",
"WTW", "WY", "WYNN", "XYL", "XYZ", "ZBH", "ZBRA"
```


## Goals

- Target Value is to predict next month return for each ticker i.e. given data through month N, predict the return for month N+1.

- Train: All tickers, all months up to cutoff (Jan. 2024)

- Test: All tickers, all months after cutoff (Jan. 2024)

- Models: Ridge Regression (L2 penalty) and Gradient Boosted Trees (separate models, ridge regression is the secondary model and can be used for feature inference)

- Make output more sophisticated than just a single predicted return value. Can output expected short-term, mid-term, long-term returns along with price prediction and confidence intervals. This will allow for more sophisticated decision making and risk management.

- Split into two models. Already saw good results with stock ranking though not as good with actual return/directional prediction so can focus one model on that and another on simply giving fair value and other statistics for the to interpret.

- Production model: `Model/notebooks/production_ranking_model.ipynb` — XGBoost `rank:ndcg` on the quarterly grain over a **core-13 raw feature set** (price_sma200/stddev/drawdown/atr/return_3m/return_12m/distance_from_52wk_high + roe/roa/debt_equity/current_ratio/cash_to_assets/fcf_to_assets + sector), walk-forward validated. An A/B on the broader universe showed the 40-feature engineered variant (vol-scaled momentum, `rk_*` cross-sectional ranks, `rel_*` momentum) *hurt* — halving pooled IC and top-10 excess — so the derived-numerator set was dropped. Optimizes the head of the ranking (top-10/top-25/top-quintile) rather than pooled return accuracy, which is what the screening product needs. Saves `Model/artifacts/ranking_ndcg.{json,meta.json}` for the service layer. Walk-forward results (26 quarters, 2019→2025, 357-ticker universe): rank IC +0.175, top-10 excess +3.13 pp/qtr (t=1.19), top-25 +4.56 (t=2.26), top-quintile +2.68 (t=2.24), precision@10 11.5% (random 3.6%), top-20 vs S&P +5.51 pp/qtr (73% of quarters).

## Roadblocks

- First roadblock encountered when trying initial training with just data from 20 tickers. Simply not enough data leading to the modeling not being able to find any real signal. All weights were near zero and model was prediciting hold/near 0.0 gain for every ticker. (Since I removed the Alpha Vantage news & sentiment api there is less rate limiting so will work to significantly increase the dataset size and then re-run training.)

- Another thing to note is that the training issues could also be due to the fact that the model is trying to predict next month returns which is more susceptible to outside noise as supposed to the more common predicting next day returns. (Will test a weekly and quarterly model to see if this amends the issue at all.)

- Noticing some improvements after switching to a quarterly model and increasing the dataset size to 120 tickers. Will continue to increase dataset size to around 500 tickers and then re-run training. Seems like between various models (XGBoost, Ridge Regression, etc.) XGBoost is performing the best and holds a higher rank IC however directional accuracy is sitting at/below the market baseline so clearly needs more work. Will continue to experiment with various features and models.

- Current direction --> Expanding dataset to 288 tickers and then re-run training. Ideally looking to see better results especially from the monthly/weekly datasets. Quarterly is more so dominated by market trends and less so by individual ticker performance so I'd like to slowly move away.

## Dataset

**Dataset**: Model/datasets/train_dataset.parquet (daily), datasets/train_dataset_monthly.parquet, datasets/train_dataset_weekly.parquet, datasets/train_dataset_quarterly.parquet — full 520-ticker universe; `train_dataset_quarterly_curated.parquet` on the 125-ticker curated list
**Feature columns**: sma_20, sma_50, sma_200, ema_12, ema_26, rsi_14, adx_14, atr_14, macd_hist, stoch_k_14, stoch_d_14, cci_20, stddev_252, max_drawdown_252, roe, roa, debt_equity, current_ratio, cash_to_assets, fcf, plus derived: price_to_sma20/50/200, atr_pct, fcf_yield
**Target**: target_return (next-month close-to-close return)

`tentative` **Walk-forward plan**: expanding window, first cutoff Jan 2024`

`features` - Notice the feature list does not include any news or sentiment features. This is due to not being able to pull news and sentiment data more than 1 year back. To avoid having a sparse dataset, the model only uses technical features. The plan is to either add news and sentiment weighting to the model down the road or create a separate model for news and sentiment features.

Feature additions: lagged features, rolling stastics, feature scaling

## Measures

1. Rank IC (primary) — within each test month, Spearman correlation of predicted vs actual. Tests ordering, which is exactly what "should I buy this vs that" needs, and is immune to the noise problem.
2. Directional accuracy — % of months sign matches. Baseline is 58.9% (returns were positive 58.9% of the time — "always predict up" scores that). Below ~59% = no edge.
3. MSE/RMSE vs baselines — predict 0, predict last month's return, predict universe mean.
4. Quintile spread (maps to your product) — sort predicted returns into quintiles each month, average realized return per quintile, check Q5−Q1 is positive and monotonic. This is the honest version of "was the model right": does the top-of-the-ranking actually outperform the bottom?
5. In terms of a direct "percent correct number", model predictions can be classified into buckets i.e. strong buy >= 10% gain, etc. and then compare to actual return buckets.