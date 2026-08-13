# README

## Main Plan

Create a stock confidence rating pipeline

- Should ideally start by focusing on 5 stocks say AAPL, GOOGL, AMZN, META, APP
- Need to plan what data will be needed and then how to collect it.
- From there, this project should focus more on the data collection side rather than the model itself so the model can be a simple baseline to get started with.

This app answers the problem: I want to buy this stock but not sure if it's a good time to buy and don't have time to research it myself. I want a simple confidence raitng and advice based on my own deterministic philosophy so that I know the app output is based on a consistent transparent model and not some black box LLM that I don't understand.

## Options
- Option 1: Have a set list of stocks to track and collect data for.
- Option 2: Allow the user to input a stock ticker and then collect data for that stock. 
I favor option 2 a bit more as it allows for more flexibility and is more user friendly. I think that it can still be simple (e.g. just output a confidence rating + advice (strong buy, buy, hold, sell, strong sell) + volatility score) and then if strong buy or buy provide a advised buy price and stop loss price as well as investing advice (e.g. long term hold, swing trade, day trade). Need to add a caching layer to avoid hitting API limits and to speed up the process. Will start with a purely deterministic model and then can possibly add a LLM call layer on top of that to provide more indepth advice and analysis.

Initial model will be a simple deterministic model that way focus can be on the data ingestion and processing. Then in post the model can be fine tuned and tested through backtesting and then possibly a LLM layer can be added on top of that to provide more indepth analysis and advice.

## Data Sources
Use 2 data sources: Finnhub and Alpha Vantage

### Finnhub
Real-time/near-real-time trade data (price, volume) via WebSocket
News sentiment scoring (aggregated news + a sentiment score attached) — this is fairly unique to Finnhub among the free tiers
Basic company fundamentals and earnings calendar (upcoming earnings dates, surprise history)
Insider transactions, analyst recommendation trends (buy/hold/sell counts over time)
Use it for: current price + trend, earnings calendar/surprises, news sentiment feed

Possible API's from Finnhub: 
**Trades**
**Market Status**
**Market Holiday**
**Company Profile 2**
**Market News**
**Company News**
**Peers (Could be useful for moat analysis)**
**Basic Financials**
**Insider Transactions**
**Insider Sentiment**
**Financials As Reported**
SEC Filings
IPO Calendar (likely useless from analysis but might be useful to display to the user)
**Recommendation Trends**
**EPS Surprises**
**Earnings Calendar**
**Quote**
**Senate Lobbying**
**USA Spending**

### Alpha Vantage
Deep historical daily/weekly/monthly OHLCV with split/dividend adjustments
Full fundamental data: income statement, balance sheet, cash flow statement (quarterly and annual, going back years)
50+ built-in technical indicators (SMA, RSI, MACD, Bollinger Bands, etc.) — computed server-side so you don't have to build them yourself
Use it for: the actual numbers that feed a DCF or comparables valuation (revenue, EPS, free cash flow, debt) — this is what Finnhub does NOT give you in depth

Possible API's from Alpha Vantage: 
Intraday
**Daily**
Daily Adjusted
**Weekly**
Weekly Adjusted
**Monthly (last trading day of each month, monthly open, monthly high, monthly low, monthly close, monthly volume)**
Monthly Adjusted (last trading day of each month, monthly open, monthly high, monthly low, monthly close, monthly adjusted close, monthly volume, monthly dividend)
**Quote Endpoint (latest price and volume)**
Realtime bulk bid & ask prices
**Ticker Search (Will help with matching user input to a valid ticker)**
**Global Market Status (Will help with market open/close status; useful for realtime)**
**Index Catalog (Full list of index symbols and names)**
Realtime put-call ratio
Realtime volume-to-open-interest ratio
Historical put-call ratio
Historical volume-to-open-interest ratio
**News Sentiment (Will be really useful for sentiment analysis)**
**Earnings call transcript (Will be really useful for sentiment analysis)**
**Top gainers/losers (Likely not useful for analysis but nice to display)**
**Insider Transactions (Overlap with Finnhub API)**
**Institutional Holdings**
**Advanced Analytics (e.g., total return, variance, auto-correlation, etc.)**
**Advanced Analytics Sliding Window (e.g., total return, variance, auto-correlation, etc.)**
**Company Overview**
Company Logo (Optional but nice for UI)
ETF Profile & Holdings (Optional but nice for UI)
Corporate Action Dividends
Corporate Action Splits
**Income Statement**
**Balance Sheet**
**Cash Flow**
**Shares Outstanding**
**Earnings History**
**Earnings Estimate**
Listing/Delisting Status
Earnings Calendar (Useful for analysis and UI display; Overlap with Finnhub API)
IPO Calendar
Commodities (Prices for Gold, Silver, Oil, etc.; will exclude for now)
Real GDP
Real GDP per Capita
Treasury Yield
Federal Funds (Interest) Rate
CPI
Inflation
Retail Sales
Durable Goods Orders
Unemployment Rate
Nonfarm Payroll
**SMA (Start of Technical Indicators List)**
**EMA**
WMA
DEMA
TEMA
TRIMA
KAMA
MAMA
T3
MACDEXT
**STOCH**
STOCHF
**RSI**
STOCHRSI
WILLR
**ADX**
ADXR
APO
PPO
MOM
BOP
**CCI**
CMO
ROC
ROCR
AROON
AROONOSC
MFI
TRIX
ULTOSC
DX
MINUS_DI
PLUS_DI
MINUS_DM
PLUS_DM
**BBANDS**
MIDPOINT
MIDPRICE
SAR
TRANGE
**ATR**
NATR
**AD**
ADOSC
**OBV**
HT_TRENDLINE
HT_SINE
HT_TRENDMODE
HT_DCPERIOD
HT_DCPHASE
HT_PHASOR

## How to make it read as a Data Engineering (DE) project, not just a "cool side project":
What would make it read as DE, not just "cool side project":
Multiple heterogeneous sources on different cadences — real-time/near-real-time price data, daily-refreshed fundamentals (revenue, earnings), and irregular news/sentiment data. That forces you to actually think about scheduling, staleness, and orchestration — not just "call three APIs in a for loop."
Real ingestion + orchestration — Dagster or Airflow scheduling the pulls, not a cron job calling a monolith script. You already know Dagster from Lindaben, so this is a chance to go deeper rather than relearn a new tool.
Incremental loads + dedup — same pattern you did at Lindaben (timestamp-based incremental loads), applied to a new domain. That's the kind of "I've done this twice, in different contexts" signal that interviewers actually trust.
A real warehouse layer, not just a dataframe — dump into DuckDB or Postgres with a proper schema (raw → staging → aggregated tables), not just compute-and-print. This is where you could stretch into Redshift/Glue if you want AWS-native keywords on the resume.
The "confidence rating" becomes the thin ML layer on top of a real pipeline, not the whole project. That's actually the more honest framing anyway — the pipeline is the hard/interesting part; the rating logic can be dead simple (rule-based even) and still make for a good demo.

