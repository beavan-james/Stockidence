# AGENTS.md — Stock Confidence Rating Pipeline

This file gives any AI coding agent (Claude Code, Cursor, etc.) working in this repo the context and rules of engagement it needs. Read this before touching code.

## 1. What this project is

A data engineering portfolio project: a stock confidence rating pipeline. The point of the project is the **pipeline**, not the model. The scoring logic should stay simple and deterministic; the engineering (ingestion, orchestration, incremental loads, staleness handling, warehouse layering) is what should read as DE work, not "cool side project."

**Product framing:** the app answers "I want to buy this stock but don't know if it's a good time, and don't have time to research it." Output is a confidence rating + advice (strong buy / buy / hold / sell / strong sell) + a separate volatility score, and for buy-rated tickers, an advised buy price, stop-loss price, and holding-style advice (long-term hold / swing trade / day trade).

**On-demand, not a fixed watchlist:** users input any ticker at request time (Option 2 from the README). This means the pipeline can't rely purely on pre-scheduled batch loads for a static universe — it needs a staleness-aware cache layer so an on-demand request for a ticker can reuse recently-fetched data instead of re-hitting Alpha Vantage's free-tier limits.

## 2. Architecture

- **Orchestration:** Dagster (already used at Lindaben — go deeper here, don't relearn a new tool)
- **Warehouse:** DuckDB, three-layer schema:
  - `raw` — landed API responses, minimally transformed
  - `staging` — typed, cleaned, deduplicated, one row per (ticker, timestamp/period)
  - `mart` — aggregated/derived tables the scoring layer reads from (includes manually-derived indicators like MACD)
- **Loading pattern:** incremental loads with watermarks per (source, ticker, endpoint) — not full refresh, not naive append. Same pattern as the Lindaben internship, applied to a new domain.
- **Cadence is heterogeneous by design** — this is a core DE signal, not an implementation detail to gloss over:
  - Near-real-time: price/quote data
  - Daily: technical indicators, market status
  - Quarterly/annual, irregular release timing: fundamentals, earnings
  - Irregular/event-driven: news, sentiment, insider transactions
- **Caching:** staleness-aware cache in front of Alpha Vantage calls specifically, since it's the tighter free-tier limit. Cache policy should differ by data type (a quote is stale in minutes; an income statement is stale in months).

## 3. Data sources

Two sources, deliberately kept on free tiers — don't suggest paid endpoints as a fix for a limitation, propose a workaround instead.

- **Finnhub** — real-time-ish trade data, news sentiment (fairly unique among free tiers), basic fundamentals/earnings calendar, insider transactions, analyst recommendation trends.
- **Alpha Vantage** — deep historical OHLCV, full fundamental statements (income/balance/cash flow), built-in technical indicators. **Exception: MACD is Premium-tier on Alpha Vantage**, so it must be derived manually in the staging layer from EMA12/EMA26, not pulled from the indicator endpoint.

## 4. Scoring model

Deterministic, rule-based, weighted formula — no black-box ML/LLM in the core score. Proposed (not yet finalized) weights:

- Valuation: 40%
- Trend: 25%
- Momentum: 15%
- Sentiment: 20%

Volatility is a **separate** output score, not blended into the confidence rating. Treat the weight split as provisional — if asked to change scoring logic, flag that the weights were a proposal, not a locked spec, and confirm before assuming a change is wanted.

An LLM layer may be added *on top of* the deterministic score later for narrative analysis — it should never replace or obscure the deterministic core. If an agent is ever asked to "just have an LLM score it," push back: that undermines the stated design philosophy (transparent, consistent, not a black box).

## 5. Coding conventions

- Python, Dagster assets/jobs for orchestration
- DuckDB for storage — write SQL that's explicit about which layer (raw/staging/mart) it reads/writes
- Config-driven API keys and rate limits — never hardcode credentials
- Prefer small, testable transformation functions over large monolithic scripts (this is a portfolio project meant to be read by interviewers — code clarity matters as much as correctness)
- When adding a new data source or endpoint, always specify: cadence, watermark key, and cache TTL before writing ingestion code

## 6. Agent behavior

### Default mode
Implement what's asked. Ask before making architectural decisions (schema changes, new orchestration patterns, weight changes) that aren't explicitly specified.

### "Grill Me" skill
Trigger: user says "grill me," "quiz me," or asks to review/explain a piece of this project (e.g. before a mock interview, after finishing a component).

When triggered, the agent stops writing code and switches to interviewer mode:
- Ask 3–5 pointed questions about the component in question (or the whole pipeline if unspecified), the way a DE interviewer would — e.g. "why watermarks instead of full refresh here," "what happens if the Alpha Vantage cache TTL expires mid-request," "why is MACD derived manually instead of pulled from the API," "why is volatility a separate score instead of folded into confidence."
- Push on weak or hand-wavy answers — ask a natural follow-up rather than accepting a surface-level response, the way a real interviewer would probe.
- Don't supply the answer up front. Let the user attempt it first; correct or fill gaps only after they've answered.
- Keep it conversational and one question at a time — not a written quiz dump.
- End by flagging any part of the pipeline the user couldn't explain cleanly, since that's the part worth re-reading or rehearsing before an actual interview.

This skill exists because the project is explicitly recruiting-prep for Summer 2027 DE internships — the goal is that every design choice in this repo can be defended out loud, not just that the code runs.

## 7. Guardrails

- Don't quietly upgrade to paid API tiers to solve a rate-limit problem — that defeats the point of the caching layer.
- Don't fold the volatility score into the confidence rating.
- Don't replace the deterministic scoring core with a model call.
- Don't treat the 40/25/15/20 weight split as final without confirming.
- Don't skip the raw/staging/mart separation for "simple" endpoints — consistency across sources is part of the DE signal.