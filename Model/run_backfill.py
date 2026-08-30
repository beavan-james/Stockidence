"""Run ingestion for all tickers directly via the engine.

Handles the watermark race condition: _touch_watermarks_for sets watermarks
for ALL tickers in the table, so we delete each ticker's price watermark
before processing to force a fresh backfill.

Usage:
    python Model/run_backfill.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.ingest.engine import IngestEngine, _PRICE_BACKFILL_DAYS
from stockidence.ingest.endpoints import on_demand_endpoints
from stockidence.mart.mart import rebuild_all_for_ticker
from stockidence.storage import Warehouse

ALL_TICKERS = [
    # existing — need price re-backfill with 5500-day lookback
    "AAPL", "AMZN", "APP", "BE", "CSCO", "DIS", "DKNG", "GOOGL",
    "INTC", "JNJ", "JPM", "KO", "META", "MSFT", "NBIS", "NVDA",
    "PLTR", "V", "WMT", "XOM",
    # new — first-time ingestion
    "UNH", "CAT", "NEE", "AMT", "BRK-B", "LIN",
]

# Skip the hot-path quote endpoint — not needed for backfill
SKIP_ENDPOINTS = {"quote"}

# Endpoints that need special dimension_key handling
SPECIAL_ENDPOINTS = {"earnings_call_transcript"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> None:
    wh = Warehouse()
    wh.init_schema()
    engine = IngestEngine(wh)

    endpoints = [ep for ep in on_demand_endpoints()
                 if ep.name not in SKIP_ENDPOINTS]

    print(f"Ingesting {len(ALL_TICKERS)} tickers × {len(endpoints)} endpoints")
    print(f"Price backfill: {_PRICE_BACKFILL_DAYS} days lookback\n")

    now = _now()
    total_api_calls = 0
    total_rows = 0
    errors = []

    for i, ticker in enumerate(ALL_TICKERS, 1):
        print(f"[{i}/{len(ALL_TICKERS)}] {ticker}")

        # Delete price watermark for this ticker to force fresh backfill.
        # _touch_watermarks_for sets watermarks for ALL tickers in the
        # table when any one ticker is processed, so we must clear it.
        with wh.connect() as con:
            con.execute(
                "DELETE FROM control.watermarks "
                "WHERE endpoint = ? AND dimension_key = ?",
                ["raw.raw_prices_daily", ticker],
            )

        ticker_calls = 0
        ticker_rows = 0

        for ep in endpoints:
            if ep.name in SPECIAL_ENDPOINTS:
                continue

            dimension = ticker
            try:
                result = engine.ingest_on_demand(ep.name, dimension, now=now)
                status = "FETCHED" if result.fetched else "fresh"
                if result.fetched:
                    ticker_calls += 1
                    ticker_rows += result.rows_written
                print(f"  {ep.name:30s} {status:8s} {result.reason}")
            except Exception as e:
                error_msg = str(e)
                print(f"  {ep.name:30s} ERROR    {error_msg[:80]}")
                errors.append((ticker, ep.name, error_msg))
                # If rate limited on AV, skip remaining AV endpoints for this ticker
                if "rate limit" in error_msg.lower() or "RateLimitError" in type(e).__name__:
                    print(f"  → Rate limited, skipping remaining AV endpoints")
                    break

        total_api_calls += ticker_calls
        total_rows += ticker_rows
        print(f"  → {ticker_calls} API calls, {ticker_rows} rows\n")

        # Brief pause between tickers to be kind to rate limits
        if i < len(ALL_TICKERS):
            time.sleep(2)

    print(f"{'='*60}")
    print(f"Ingestion complete: {total_api_calls} API calls, {total_rows} rows")
    if errors:
        print(f"\n{len(errors)} errors:")
        for ticker, ep, msg in errors:
            print(f"  {ticker}/{ep}: {msg[:100]}")

    print(f"\nRebuilding derived tables for all tickers...")

    for i, ticker in enumerate(ALL_TICKERS, 1):
        counts = rebuild_all_for_ticker(wh, ticker)
        print(f"[{i}/{len(ALL_TICKERS)}] {ticker}: {counts}")

    print(f"\nDone. All tickers ingested and derived tables rebuilt.")


if __name__ == "__main__":
    main()
