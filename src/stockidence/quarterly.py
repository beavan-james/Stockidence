"""Quarterly model-refresh pipeline steps (Dagster ops delegate here).

Chain: refresh whole ticker universe (incremental) -> rebuild the quarterly
training dataset -> re-execute the ranking notebook (which retrains and
exports the ranking snapshot to mart.model_rankings).

Heavy ML imports (pandas, nbclient) stay inside function bodies so importing
this module — and therefore Dagster definitions — never requires them.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .config import repo_root

if TYPE_CHECKING:
    from .storage import Warehouse

REPO_ROOT = repo_root()
SCRIPTS_DIR = REPO_ROOT / "Model" / "scripts"
DATASETS_DIR = REPO_ROOT / "Model" / "datasets"
NOTEBOOK_PATH = REPO_ROOT / "Model" / "notebooks" / "production_ranking_model.ipynb"
QUARTERLY_PARQUET = DATASETS_DIR / "train_dataset_quarterly.parquet"
# Latest, not-yet-realized quarter: what the website ranking is scored on.
SCORE_PARQUET = DATASETS_DIR / "score_dataset_quarterly.parquet"

# Dedicated kernel provisioned at retrain time so notebook execution never
# depends on (or clobbers) the user's own kernelspecs.
KERNEL_NAME = "stockidence"


def quarterly_universe(warehouse: Warehouse | None = None) -> list[str]:
    """Full refresh universe: every ticker in the warehouse.

    Unions tickers with landed prices or a company profile (seed backfill
    plus anything users have looked up since) with ALL_TICKERS from
    Model/scripts/run_backfill.py, so a fresh warehouse still gets seeded.
    """
    spec = importlib.util.spec_from_file_location(
        "run_backfill", SCRIPTS_DIR / "run_backfill.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tickers = [t.strip().upper() for t in module.ALL_TICKERS if t.strip()]

    if warehouse is not None:
        with warehouse.connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT ticker FROM raw.raw_prices_daily
                UNION
                SELECT ticker FROM raw.raw_company_profile
                ORDER BY ticker
                """
            ).fetchall()
        tickers += [str(t).strip().upper() for (t,) in rows if t and str(t).strip()]

    # Preserve order (seed list first), drop duplicates.
    return list(dict.fromkeys(tickers))


def rebuild_quarterly_dataset() -> dict:
    """Rebuild train_dataset_quarterly.parquet — same as the CLI with --freq quarterly.

    Also writes score_dataset_quarterly.parquet: the newest quarter's
    snapshot, whose forward return isn't known yet. The notebook ranks that
    cohort for the website instead of the last (already realized) training
    quarter.
    """
    spec = importlib.util.spec_from_file_location(
        "build_dataset", SCRIPTS_DIR / "build_dataset.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    full = module.build_dataset(freq="quarterly", keep_unlabeled=True)
    labeled = full["target_return"].notna()
    dataset = full[labeled]

    # Price freshness: a ticker whose prices stopped early still gets a row
    # for the newest quarter, but its features are a stale snapshot.
    from .storage import Warehouse

    with Warehouse().connect(read_only=True) as con:
        last_trade = dict(con.execute(
            "SELECT ticker, MAX(date) FROM staging.stg_prices_daily GROUP BY ticker"
        ).fetchall())
    newest = max(last_trade.values())
    fresh = {t for t, d in last_trade.items() if (newest - d).days <= 7}

    # Score the newest quarter that most tickers have reached — a few
    # tickers with an early bar of the next quarter must not become the
    # whole website ranking — using only tickers with fresh prices.
    unlabeled = full[~labeled & full["ticker"].isin(fresh)]
    counts = unlabeled.groupby("date")["ticker"].nunique()
    latest = counts[counts >= 0.5 * counts.max()].index.max()
    score = unlabeled[unlabeled["date"] == latest]

    # Refuse to publish a ranking over a fraction of the universe (e.g. the
    # price refresh failed for most tickers): fail loudly and leave the
    # current website ranking in place.
    # Reference: typical recent cohort (the newest training quarter is thin
    # too when prices are stale, so it can't be the yardstick).
    last_cohort = int(dataset.groupby("date")["ticker"].nunique().tail(4).median())
    n_score = int(score["ticker"].nunique())
    if n_score < 0.5 * last_cohort:
        stale = sorted(set(last_trade) - fresh)
        raise RuntimeError(
            f"only {n_score} tickers have fresh prices for the {latest} cohort "
            f"(recent cohorts: ~{last_cohort}); {len(stale)} tickers' prices are "
            f"more than 7 days behind {newest}, e.g. {', '.join(stale[:20])}. "
            "Check the refresh step's failed fetches, then re-run."
        )
    QUARTERLY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(QUARTERLY_PARQUET, index=False)
    score.to_parquet(SCORE_PARQUET, index=False)
    return {
        "parquet": str(QUARTERLY_PARQUET),
        "rows": int(len(dataset)),
        "tickers": int(dataset["ticker"].nunique()),
        "date_min": str(dataset["date"].min()),
        "date_max": str(dataset["date"].max()),
        "score_cohort": str(latest),
        "score_tickers": int(score["ticker"].nunique()),
        "newest_price": str(newest),
        "stale_price_tickers": sorted(set(last_trade) - fresh),
        "recent_cohort_sizes": {
            str(d.date()): int(n)
            for d, n in dataset.groupby("date")["ticker"].nunique().tail(4).items()
        },
    }


def retrain_ranking_model() -> dict:
    """Re-execute the ranking notebook in place (retrains + exports snapshot).

    Runs the stockidence kernel with its cwd at the notebook directory so the
    notebook's own path resolution (Model/ vs Model/notebooks/) keeps working,
    and with src/ on PYTHONPATH so `import stockidence` resolves.
    """
    import nbformat
    from nbclient import NotebookClient

    from ipykernel.kernelspec import install as install_kernel

    install_kernel(user=True, kernel_name=KERNEL_NAME, display_name="Stockidence")

    src_dir = str(Path(__file__).resolve().parent.parent)
    env_path = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = src_dir + (os.pathsep + env_path if env_path else "")

    nb = nbformat.read(str(NOTEBOOK_PATH), as_version=4)
    client = NotebookClient(
        nb,
        timeout=3600,
        kernel_name=KERNEL_NAME,
        resources={"metadata": {"path": str(NOTEBOOK_PATH.parent)}},
    )
    client.execute()
    nbformat.write(nb, str(NOTEBOOK_PATH))
    return {"notebook": str(NOTEBOOK_PATH), "cells_executed": len(nb.cells)}
