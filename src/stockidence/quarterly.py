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

if TYPE_CHECKING:
    from .storage import Warehouse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "Model" / "scripts"
DATASETS_DIR = REPO_ROOT / "Model" / "datasets"
NOTEBOOK_PATH = REPO_ROOT / "Model" / "notebooks" / "production_ranking_model.ipynb"
QUARTERLY_PARQUET = DATASETS_DIR / "train_dataset_quarterly.parquet"

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
    """Rebuild train_dataset_quarterly.parquet — same as the CLI with --freq quarterly."""
    spec = importlib.util.spec_from_file_location(
        "build_dataset", SCRIPTS_DIR / "build_dataset.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dataset = module.build_dataset(freq="quarterly")
    QUARTERLY_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_parquet(QUARTERLY_PARQUET, index=False)
    return {
        "parquet": str(QUARTERLY_PARQUET),
        "rows": int(len(dataset)),
        "tickers": int(dataset["ticker"].nunique()),
        "date_min": str(dataset["date"].min()),
        "date_max": str(dataset["date"].max()),
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
