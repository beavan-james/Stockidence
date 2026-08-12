# README

## Main Plan

Create a stock confidence rating pipeline

- Should ideally start by focusing on 5 stocks say AAPL, GOOGL, AMZN, META, APP
- Need to plan what data will be needed and then how to collect it.
- From there, this project should focus more on the data collection side rather than the model itself so the model can be a simple baseline to get started with.

## Options
- Option 1: Have a set list of stocks to track and collect data for.
- Option 2: Allow the user to input a stock ticker and then collect data for that stock. 
I favor option 2 a bit more as it allows for more flexibility and is more user friendly. I think that it can still be simple (e.g. just output a confidence rating + advice (strong buy, buy, hold, sell, strong sell) + volatility score) and then if strong buy or buy provide a advised buy price and stop loss price as well as investing advice (e.g. long term hold, swing trade, day trade). Need to add a caching layer to avoid hitting API limits and to speed up the process. Will start with a purely deterministic model and then can possibly add a LLM call layer on top of that to provide more indepth advice and analysis.

## Data Sources
Use 2 data sources: Finnhub and Alpha Vantage
Finnhub
Real-time/near-real-time trade data (price, volume) via WebSocket
News sentiment scoring (aggregated news + a sentiment score attached) — this is fairly unique to Finnhub among the free tiers
Basic company fundamentals and earnings calendar (upcoming earnings dates, surprise history)
Insider transactions, analyst recommendation trends (buy/hold/sell counts over time)
Use it for: current price + trend, earnings calendar/surprises, news sentiment feed

Alpha Vantage
Deep historical daily/weekly/monthly OHLCV with split/dividend adjustments
Full fundamental data: income statement, balance sheet, cash flow statement (quarterly and annual, going back years)
50+ built-in technical indicators (SMA, RSI, MACD, Bollinger Bands, etc.) — computed server-side so you don't have to build them yourself
Use it for: the actual numbers that feed a DCF or comparables valuation (revenue, EPS, free cash flow, debt) — this is what Finnhub does NOT give you in depth

## How to make it read as a Data Engineering (DE) project, not just a "cool side project":
What would make it read as DE, not just "cool side project":
Multiple heterogeneous sources on different cadences — real-time/near-real-time price data, daily-refreshed fundamentals (revenue, earnings), and irregular news/sentiment data. That forces you to actually think about scheduling, staleness, and orchestration — not just "call three APIs in a for loop."
Real ingestion + orchestration — Dagster or Airflow scheduling the pulls, not a cron job calling a monolith script. You already know Dagster from Lindaben, so this is a chance to go deeper rather than relearn a new tool.
Incremental loads + dedup — same pattern you did at Lindaben (timestamp-based incremental loads), applied to a new domain. That's the kind of "I've done this twice, in different contexts" signal that interviewers actually trust.
A real warehouse layer, not just a dataframe — dump into DuckDB or Postgres with a proper schema (raw → staging → aggregated tables), not just compute-and-print. This is where you could stretch into Redshift/Glue if you want AWS-native keywords on the resume.
The "confidence rating" becomes the thin ML layer on top of a real pipeline, not the whole project. That's actually the more honest framing anyway — the pipeline is the hard/interesting part; the rating logic can be dead simple (rule-based even) and still make for a good demo.

