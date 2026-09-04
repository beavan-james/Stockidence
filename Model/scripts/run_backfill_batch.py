"""Run backfill for a batch of tickers (diverse sector expansion).

Thin CLI over stockidence.ingest.refresh.refresh_tickers: full price
backfill per ticker (watermarks wiped first), derived rebuilds inline.
Edit BATCH_TICKERS, then run:

    python Model/scripts/run_backfill_batch.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.ingest.engine import _PRICE_BACKFILL_DAYS, IngestEngine
from stockidence.ingest.refresh import refresh_tickers
from stockidence.storage import Warehouse


BATCH_TICKERS: list[str] = [

]


def main() -> None:
    wh = Warehouse()
    wh.init_schema()
    engine = IngestEngine(wh)

    print(f"Ingesting current batch: {len(BATCH_TICKERS)} tickers", flush=True)
    print(f"Price backfill lookback: {_PRICE_BACKFILL_DAYS} days", flush=True)

    summary = refresh_tickers(engine, BATCH_TICKERS, full_backfill=True)

    print(f"\n{'='*60}", flush=True)
    print(
        f"Batch complete: {summary['api_calls']} API calls, "
        f"{summary['rows_written']} rows",
        flush=True,
    )
    if summary["errors"]:
        print(f"\n{len(summary['errors'])} errors:", flush=True)
        for err in summary["errors"]:
            print(f"  {err['ticker']}/{err['endpoint']}: {err['error'][:100]}", flush=True)


if __name__ == "__main__":
    main()
