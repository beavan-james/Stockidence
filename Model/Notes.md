# Notes about Model Fitting

## Dataset Ticker List

AAPL, AMZN, APP, BE, CSCO, DIS, DKNG, GOOGL, INTC, JNJ, JPM, KO, META, 
MSFT, NBIS, PLTR, NVDA, V, WMT, XOM, UNH, CAT, NEE, AMT, BRK-B, LIN

## Goals

Target value is predict the stock return for the next month. 
Data should go back as far as possible. 
Given data through month N, predict the return for month N+1.
Need to pick a set of tickers I can use to train the model. Good variety is better, so should use ones we already have data for like AAPL, AMZN, META, CSCO, APP, DKNG, etc.
Need to create the feature data set. Will be one table one row per (ticker, month) with all the features for that ticker. Seperate next month return table. 
Can do a rolling window so the model will use all prior data and then predict next month return for each ticker on rolling time window.
Model should predict next month return and then at the end compare the predicted return to the actual return and see how well it did.

Train: All tickers, all months up to cutoff (Jan. 2024)
Test: All tickers, all months after cutoff (Jan. 2024)
Can do a walking window so the train set is all months up to month N and then test on month N+1. Then move the window forward one month and repeat. This will give a better idea of how well the model does over time.

## Thoughts

13. Do a full training of a completely different model on training data set for new more transportable model. (status: in progress)
- Decide can either do various modes (daily, monthly, yearly) or just do one yearly model which tries to predict the next year of stock prices. Various modes would allow for broader use case but requires training 3 models instead of 1.
- Can likely use some form of non-linear regression model to predict stock prices. Would be supervised since we have the past set of stock prices to train on but we also will need to pull the past data for the stock prices to train on. One thing to note is that if training on a yearly prediction model, the grain would be less and we would neeed to pull more tickers data to get a larger set whereas daily grain would be highest and monthly grain would be in between (and may be the sweet spot we are looking for).
Can use numpy for the 