"""One-time backfill setup: reset price watermarks + queue all tickers.

Run this script once after bumping _PRICE_BACKFILL_DAYS to trigger
a full history re-fetch for all tickers (existing + new).

Usage:
    python Model/setup_backfill.py

The Dagster ticker_request_sensor will pick up the pending requests
and materialize ticker_data for each ticker, which triggers the full
on-demand ingestion pipeline (prices, fundamentals, news, etc.).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Add repo root to path so we can import stockidence
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.storage import Warehouse

EXISTING_TICKERS = [
    "AAPL", "AMZN", "APP", "BE", "CSCO", "DIS", "DKNG", "GOOGL",
    "INTC", "JNJ", "JPM", "KO", "META", "MSFT", "NBIS", "NVDA",
    "PLTR", "V", "WMT", "XOM",
]

NEW_TICKERS = ["UNH", "CAT", "NEE", "AMT", "BRK-B", "LIN"]


def main() -> None:
    wh = Warehouse()
    now = datetime.now(timezone.utc)

    # 1. Delete price watermarks so existing tickers get re-fetched
    #    with the new 5500-day lookback (Phase 1a).
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

    # 2. Queue all tickers for ingestion (existing + new).
    all_tickers = EXISTING_TICKERS + NEW_TICKERS
    for ticker in all_tickers:
        wh.request_ticker(ticker, requested_at=now)
        status = "existing" if ticker in EXISTING_TICKERS else "NEW"
        print(f"Queued {ticker:8s} [{status}]")

    # 3. Summary
    pending = wh.pending_ticker_requests()
    print(f"\nDone. {len(pending)} tickers pending in control.ticker_requests.")
    print("Start the Dagster daemon to process the sensor, or trigger manually.")


if __name__ == "__main__":
    main()
