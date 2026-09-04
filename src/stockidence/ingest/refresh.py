"""Shared per-ticker refresh runner: ingest + derived rebuilds (+ optional scoring).

This is the single implementation behind bulk refreshes. Callers:

* the quarterly Dagster job — whole universe, incremental (watermarks intact,
  so the staleness gate only fetches what's new since last quarter)
* the frontend-triggered ``refresh_tickers`` job — a few tickers, incremental
  as well: with no watermark on record the gate pulls full history
  automatically, so no special-casing is needed for new tickers
* ``Model/scripts/run_backfill*.py`` — thin CLI wrappers over this module

Retry policy: every failed endpoint fetch is retried up to ``max_attempts``
times with a short backoff, then recorded and skipped. A single bad ticker
never aborts the run — unlike the original backfill scripts, which stopped
the whole universe on the first rate-limit error.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from .endpoints import on_demand_endpoints
from .engine import IngestEngine
from ..mart.mart import rebuild_all_for_ticker
from ..mart.scoring import score_ticker
from ..storage import Warehouse

# Hot-path quote endpoint — not needed for refreshes. ticker_news is the
# only Alpha Vantage endpoint and the ML feature set no longer uses
# news/sentiment (also avoids the 25/day free-tier limit entirely).
SKIP_ENDPOINTS = frozenset({"quote", "ticker_news"})

# Needs special dimension_key handling (SYM|Q|YYYY); only the ticker_data
# asset resolves that, so the runner skips it like the backfill scripts do.
SPECIAL_ENDPOINTS = frozenset({"earnings_call_transcript"})

# Pause between fetch attempts so a flapping provider can recover.
RETRY_BACKOFF_SECONDS = 5.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def refresh_tickers(
    engine: IngestEngine,
    tickers: Sequence[str],
    *,
    full_backfill: bool = False,
    max_attempts: int = 3,
    score: bool = False,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Refresh raw + derived data for ``tickers``. Returns a JSON-safe summary.

    ``full_backfill`` wipes each ticker's price watermark first to force a
    complete history re-pull; otherwise the staleness gate fetches only what
    is new (the quarterly-refresh mode — only the recent quarter is missing).
    ``score`` also persists a fresh confidence rating per ticker (the
    frontend-triggered mode, so the rating appears without a second pass).
    """
    warehouse: Warehouse = engine.warehouse
    endpoints = [ep for ep in on_demand_endpoints() if ep.name not in SKIP_ENDPOINTS]
    now = _now()
    emit = log or (lambda msg: print(msg, flush=True))

    total_calls = total_rows = 0
    errors: list[dict[str, str]] = []
    processed = 0

    for i, ticker in enumerate(tickers, 1):
        emit(f"[{i}/{len(tickers)}] {ticker}")

        if full_backfill:
            with warehouse.connect() as con:
                con.execute(
                    "DELETE FROM control.watermarks "
                    "WHERE endpoint = ? AND dimension_key = ?",
                    ["raw.raw_prices_daily", ticker],
                )

        ticker_calls = ticker_rows = 0
        for ep in endpoints:
            if ep.name in SPECIAL_ENDPOINTS:
                continue
            result = None
            last_error: str | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = engine.ingest_on_demand(ep.name, ticker, now=now)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001 — record and retry
                    last_error = str(exc)
                    emit(f"  {ep.name:30s} attempt {attempt}/{max_attempts} failed: {last_error[:100]}")
                    if attempt < max_attempts:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            if last_error is not None:
                errors.append({"ticker": ticker, "endpoint": ep.name, "error": last_error})
                emit(f"  {ep.name:30s} ERROR    giving up after {max_attempts} attempts")
                continue
            assert result is not None
            status = "FETCHED" if result.fetched else "fresh"
            if result.fetched:
                ticker_calls += 1
                ticker_rows += result.rows_written
            emit(f"  {ep.name:30s} {status:8s} {result.reason}")

        total_calls += ticker_calls
        total_rows += ticker_rows
        emit(f"  -> {ticker_calls} API calls, {ticker_rows} rows")

        counts = rebuild_all_for_ticker(warehouse, ticker)
        emit(f"  -> derived: {counts}")

        if score:
            rating = score_ticker(warehouse, ticker)
            emit(f"  -> score: {rating.rating} (confidence {rating.confidence_score:.1f})")

        processed += 1

    return {
        "tickers": list(tickers),
        "processed": processed,
        "api_calls": total_calls,
        "rows_written": total_rows,
        "errors": errors,
    }
