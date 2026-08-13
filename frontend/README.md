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

- `frontend/stockidence_app/service/warehouse.py` — reads `mart.confidence_ratings`, `mart.rating_components`, `mart.buy_plans` (schema mirrors the pipeline's mart layer). Configure the DB path with the `STOCKIDENCE_DB` env var (default `data/stockidence.duckdb`).
- `frontend/stockidence_app/service/demo.py` — deterministic sample generator, used as a fallback so the UI is fully demoable while the pipeline is being built out. Demo output is visibly labeled in the UI.

Scoring/weight changes live in the pipeline, not the frontend; the frontend just renders whatever the mart returns.

## Tests

```bash
cd frontend
uv run python -m pytest tests -q
```