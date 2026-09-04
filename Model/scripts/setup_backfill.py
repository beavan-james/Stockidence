"""One-time full backfill: reset price watermarks + refresh every ticker.

Run this script once after bumping _PRICE_BACKFILL_DAYS to trigger
a full history re-fetch for the whole universe.

Usage:
    python Model/scripts/setup_backfill.py

Push model: runs refresh_tickers(full_backfill=True) directly — no sensor
queue involved. Equivalent to launching the refresh_tickers job with the
full universe, plus the watermark wipe.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to path so we can import stockidence
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.ingest.engine import IngestEngine
from stockidence.ingest.refresh import refresh_tickers
from stockidence.quarterly import quarterly_universe
from stockidence.storage import Warehouse


def main() -> None:
    wh = Warehouse()
    wh.init_schema()
    engine = IngestEngine(wh)

    # 1. Delete price watermarks so every ticker gets re-fetched
    #    with the full lookback.
    with wh.connect() as con:
        before = con.execute(
            "SELECT COUNT(*) FROM control.watermarks WHERE endpoint = ?",
            ["raw.raw_prices_daily"],
        ).fetchone()[0]
        con.execute(
            "DELETE FROM control.watermarks WHERE endpoint = ?",
            ["raw.raw_prices_daily"],
        )
        print(f"Deleted {before} price watermarks (raw.raw_prices_daily)")

    # 2. Refresh the whole universe with full backfills.
    universe = quarterly_universe()
    print(f"Refreshing {len(universe)} tickers (full backfill)...")
    summary = refresh_tickers(engine, universe, full_backfill=True)

    # 3. Summary
    print(f"\nDone. {summary['processed']} tickers refreshed, "
          f"{summary['api_calls']} API calls, {summary['rows_written']} rows.")
    if summary["errors"]:
        print(f"{len(summary['errors'])} errors:")
        for err in summary["errors"]:
            print(f"  {err['ticker']}/{err['endpoint']}: {err['error'][:100]}")


if __name__ == "__main__":
    main()
