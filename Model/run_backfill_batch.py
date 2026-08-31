"""Run backfill for batch-1 new tickers only (diverse sector expansion).

Safer than re-running the whole ALL_TICKERS universe: processes just the
10 new tickers so existing ones are not re-fetched. Clears each ticker's
price watermark first to force a fresh 5500-day backfill, mirrors
run_backfill.py's loop.

Usage:
    python Model/run_backfill_batch.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.ingest.endpoints import on_demand_endpoints
from stockidence.ingest.engine import IngestEngine, _PRICE_BACKFILL_DAYS
from stockidence.mart.mart import rebuild_all_for_ticker
from stockidence.storage import Warehouse

BATCH_TICKERS = [
    "DAL", "UAL", "PEP", "DHI", "TSLA", "GM", "ADM", "LEN", "MCO", "CMG",
]

SKIP_ENDPOINTS = {"quote", "ticker_news"}
SPECIAL_ENDPOINTS = {"earnings_call_transcript"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main() -> None:
    wh = Warehouse()
    wh.init_schema()
    engine = IngestEngine(wh)

    endpoints = [ep for ep in on_demand_endpoints()
                 if ep.name not in SKIP_ENDPOINTS]

    print(f"Ingesting batch-1: {len(BATCH_TICKERS)} new tickers "
          f"x {len(endpoints)} endpoints", flush=True)
    print(f"Price backfill lookback: {_PRICE_BACKFILL_DAYS} days", flush=True)

    now = _now()
    total_calls = total_rows = 0
    errors = []

    for i, ticker in enumerate(BATCH_TICKERS, 1):
        print(f"\n[{i}/{len(BATCH_TICKERS)}] {ticker}", flush=True)

        # Force a fresh full price backfill for this ticker.
        with wh.connect() as con:
            con.execute(
                "DELETE FROM control.watermarks "
                "WHERE endpoint = ? AND dimension_key = ?",
                ["raw.raw_prices_daily", ticker],
            )

        ticker_calls = ticker_rows = 0
        for ep in endpoints:
            if ep.name in SPECIAL_ENDPOINTS:
                continue
            try:
                result = engine.ingest_on_demand(ep.name, ticker, now=now)
                status = "FETCHED" if result.fetched else "fresh"
                if result.fetched:
                    ticker_calls += 1
                    ticker_rows += result.rows_written
                print(f"  {ep.name:30s} {status:8s} {result.reason}", flush=True)
            except Exception as e:
                msg = str(e)
                print(f"  {ep.name:30s} ERROR    {msg[:80]}", flush=True)
                errors.append((ticker, ep.name, msg))
                if "rate limit" in msg.lower():
                    print(f"  -> RATE LIMITED on {ticker}/{ep.name}. Stopping.", flush=True)
                    raise SystemExit(1)

        total_calls += ticker_calls
        total_rows += ticker_rows
        print(f"  -> {ticker_calls} API calls, {ticker_rows} rows", flush=True)

        counts = rebuild_all_for_ticker(wh, ticker)
        print(f"  -> derived: {counts}", flush=True)

        if i < len(BATCH_TICKERS):
            time.sleep(2)

    print(f"\n{'='*60}", flush=True)
    print(f"Batch complete: {total_calls} API calls, {total_rows} rows", flush=True)
    if errors:
        print(f"\n{len(errors)} errors:", flush=True)
        for t, ep, msg in errors:
            print(f"  {t}/{ep}: {msg[:100]}", flush=True)


if __name__ == "__main__":
    main()
