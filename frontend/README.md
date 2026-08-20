# Stockidence Frontend

Reflex app for the stock **confidence rating pipeline**. Lets a user enter any ticker and get a confidence rating, advice (strong buy / buy / hold / sell / strong sell), a separate volatility score, and — for buy-rated tickers — an advised buy price, stop-loss price, and holding-style advice.

## Run

```bash
cd frontend
uv venv --system-site-packages
uv pip install -r requirements.txt
uv run reflex run --env dev
```

Open http://localhost:3000.

## Data layer

The UI never talks to the API providers directly. It reads from the **mart** layer of the DuckDB warehouse:

- `frontend/stockidence_app/service/warehouse.py` — reads the presentation views `mart.confidence_ratings`, `mart.rating_components`, `mart.buy_plans`, and `mart.category_scores` (thin views over the pipeline's `m_*` snapshot tables, created by the pipeline's `init_schema`). Configure the DB path with the `STOCKIDENCE_DB` env var (default: the repo's `data/stockidence.duckdb`).
- `frontend/stockidence_app/service/sub_scores.py` — human-readable sub-score labels/sources/direction rules (display text only; scores and weights always come from the mart).
- `frontend/stockidence_app/service/market.py` — market-wide widgets (macro, commodities, movers, calendars, news) read from the raw layer, which doubles as the staleness-aware cache.
- `frontend/stockidence_app/service/demo.py` — deterministic sample generator, fallback only when the warehouse is entirely absent.

Lookup flow: a ticker with a warehouse rating renders it (source badge "Warehouse data"). An unknown ticker is **enqueued** in `control.ticker_requests` (source "Computing…") — the Dagster sensor consumes that queue, runs the pipeline, and the rating appears on the next lookup. Demo data appears only when no warehouse file exists at all.

Scoring/weight changes live in the pipeline, not the frontend; the frontend just renders whatever the mart returns. The one exception is display labeling (category names, sub-score labels/sources), which lives in `sub_scores.py` and `state.py` — the numeric weights and scores themselves always come from the mart (`model_weights`, `category_scores`, `rating_components`).

## Tests

```bash
cd frontend
uv run python -m pytest tests -q
```