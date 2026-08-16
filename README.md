# Stockidence — Stock Confidence Rating Pipeline

## What this is

A data engineering portfolio project: a **stock confidence rating pipeline**.
The point is the pipeline — ingestion, orchestration, incremental loads,
staleness handling, warehouse layering — not the model. The scoring logic is a
simple, deterministic rule set kept deliberately transparent (never a black
box).

**The problem it answers:** *"I want to buy this stock but don't know if it's a
good time, and I don't have time to research it."* The app outputs, for any
ticker:

- a **confidence rating** + advice (`strong buy / buy / hold / sell / strong sell`)
- a **separate volatility score** (never blended into the confidence rating)
- for buy-rated tickers: an **advised buy price**, **stop-loss price**, and
  **holding-style advice** (long-term hold / swing trade / day trade)

**On-demand, not a fixed watchlist.** Users enter any ticker at request time.
That means the pipeline can't rely on pre-scheduled batch loads for a static
universe — it needs a staleness-aware cache layer in front of the API calls so
an on-demand request can reuse recently-fetched data instead of re-hitting
free-tier rate limits. See `ARCHITECTURE.md` for the data flow.

## Data Sources

Sources are deliberately limited to free tiers — rate limits are a feature the
caching layer exists to solve, not a problem to buy around.

| Source        | Used for                                                                  |
| ------------- | ------------------------------------------------------------------------- |
| **Finnhub**   | Company profile 2, basic & as-reported financials, EPS surprises, insider sentiment, recommendation trends, peers, IPO & earnings calendars, quote, symbol search, market status/holiday |
| **Twelve Data** | Price time series (`interval=1day`, split-adjusted); weekly/monthly are resampled downstream in the warehouse, not fetched |
| **Alpha Vantage** | Market news & sentiment, top gainers/losers, earnings call transcript, macro indicators (inflation, CPI, unemployment, fed funds, natural gas, real GDP), commodities (gold/silver) |

The full endpoint list — grouped by the scoring category each feeds — is in
[`API.md`](API.md).

> **Exception:** MACD is Premium-tier on Alpha Vantage, so it is **derived
> manually in the staging layer** from EMA12/EMA26, never pulled from the
> indicator endpoint. Technical indicators and volatility analytics are
> computed in-Dagster from raw price bars as pure derivations, not API calls.

## Scoring Model

Deterministic, rule-based, weighted formula — no ML/LLM in the core score.
Weights are **provisional** (Valuation 52%, Trend 21%, Sentiment 21%, Moat 6%;
volatility is a separate output). See [`MODEL.md`](MODEL.md) for sub-scores,
fair-value methodology, and thresholds.

An LLM layer may be added *on top of* the deterministic score later for
narrative analysis — it will never replace or obscure the deterministic core.

## Architecture

- **Orchestration:** Dagster (assets/jobs), incremental loads with
  watermark-based staleness gates per (source, ticker, endpoint)
- **Warehouse:** DuckDB, three-layer schema `raw → staging → mart`
- **Cadence is heterogeneous by design:**
  - Near-real-time: price/quote data (Twelve Data, Finnhub quote)
  - Daily: persistent market data (movers, IPO/earnings calendars, news)
  - Monthly: commodities, macro indicators
  - Quarterly/irregular: fundamentals, earnings, transcripts
- **Caching:** staleness-aware cache in front of API calls; policy differs by
  data type (a quote is stale in minutes, an income statement in months)

---

The rest of this file is the original planning notes, preserved for context.

## Main Plan

Create a stock confidence rating pipeline.

- Should ideally start by focusing on 5 stocks say AAPL, GOOGL, AMZN, META, APP.
- Need to plan what data will be needed and then how to collect it.
- From there, this project should focus more on the data collection side
  rather than the model itself so the model can be a simple baseline to get
  started with.

The app answers the problem: *I want to buy this stock but not sure if it's a
good time to buy and don't have time to research it myself. I want a simple
confidence rating and advice based on my own deterministic philosophy so that
I know the app output is based on a consistent transparent model and not some
black box LLM that I don't understand.*

## Options

- **Option 1:** Have a set list of stocks to track and collect data for.
- **Option 2:** Allow the user to input a stock ticker and then collect data
  for that stock.

I favor option 2 a bit more as it allows for more flexibility and is more
user friendly. I think that it can still be simple (e.g. just output a
confidence rating + advice (strong buy, buy, hold, sell, strong sell) +
volatility score) and then if strong buy or buy provide an advised buy price
and stop-loss price as well as investing advice (e.g. long term hold, swing
trade, day trade). Need to add a caching layer to avoid hitting API limits
and to speed up the process. Will start with a purely deterministic model and
then can possibly add an LLM call layer on top of that to provide more
in-depth advice and analysis.

Initial model will be a simple deterministic model that way focus can be on
the data ingestion and processing. Then in post the model can be fine-tuned
and tested through backtesting and then possibly an LLM layer can be added on
top of that to provide more in-depth analysis and advice.

## How to make it read as a Data Engineering (DE) project, not just a "cool side project"

What would make it read as DE, not just "cool side project":

1. **Multiple heterogeneous sources on different cadences** — near-real-time
   price data, daily-refreshed fundamentals and persistent market data, and
   irregular news/sentiment data. That forces you to actually think about
   scheduling, staleness, and orchestration — not just "call three APIs in a
   for loop."
2. **Real ingestion + orchestration** — Dagster scheduling the pulls, not a
   cron job calling a monolith script. We already know Dagster from the
   Lindaben internship, so this is a chance to go deeper rather than relearn
   a new tool.
3. **Incremental loads + dedup** — the same pattern used at Lindaben
   (timestamp-based incremental loads / watermark-based staleness gates),
   applied to a new domain. That's the kind of "I've done this twice, in
   different contexts" signal interviewers actually trust.
4. **A real warehouse layer, not just a dataframe** — DuckDB with a proper
   `raw → staging → mart` schema, not compute-and-print. Stretch: Redshift/Glue
   for AWS-native keywords on the resume.
5. **The "confidence rating" is the thin layer on top of a real pipeline**,
   not the whole project. The pipeline is the hard/interesting part; the
   rating logic is deliberately simple (rule-based) and still makes a good
   demo.