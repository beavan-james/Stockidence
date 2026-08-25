# Stockidence Frontend

React SPA for the stock **confidence rating pipeline**. Enter any ticker and get a confidence rating, advice (strong buy / buy / hold / sell / strong sell), a separate volatility score, and — for buy-rated tickers — an advised buy price, stop-loss price, and holding-style advice.

## Stack

- **UI:** Vite + React 19 + TypeScript, Tailwind CSS v4 (dark token set in `frontend-react/src/index.css`), TanStack Query for data fetching/polling
- **API:** FastAPI (`src/stockidence/api/`) — thin HTTP layer over `stockidence.service`, which reads the DuckDB warehouse

## Run

```bash
# terminal 1 — API
uv run uvicorn stockidence.api.app:app --reload

# terminal 2 — UI (dev server proxies /api to :8000)
cd frontend-react
npm install
npm run dev
```

Open http://localhost:5173.

## Data flow

The UI never talks to the API providers directly. FastAPI reads the **mart** layer of the DuckDB warehouse via the service functions:

- `src/stockidence/service/warehouse.py` — reads the presentation views `mart.confidence_ratings`, `mart.rating_components`, `mart.buy_plans`, `mart.category_scores` (thin views over the pipeline's `m_*` snapshot tables, created by the pipeline's `init_schema`). Configure the DB path with the `STOCKIDENCE_DB` env var (default: the repo's `data/stockidence.duckdb`).
- `src/stockidence/service/sub_scores.py` — human-readable sub-score labels/sources/direction rules, served via `/api/component-spec`.
- `src/stockidence/service/market.py` — market-wide widgets (macro, commodities, movers, calendars, news) read from the raw layer, which doubles as the staleness-aware cache.
- `src/stockidence/service/demo.py` — deterministic sample generator, fallback only when the warehouse is entirely absent.

Lookup flow: a ticker with a warehouse rating renders it immediately; if the snapshot is >1 day old it re-renders from the old data while flagging "Refreshing" and requeueing compute. An unknown-but-covered ticker is **enqueued** in `control.ticker_requests` ("pending") — the Dagster sensor consumes that queue, runs the pipeline, and the SPA polls every 10s until the rating lands. Demo data appears only when no warehouse file exists at all.

Scoring/weight changes live in the pipeline, not the frontend; the frontend just renders whatever the mart returns.

## Tests

```bash
cd frontend
uv run python -m pytest tests -q
```
