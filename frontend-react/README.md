# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

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

