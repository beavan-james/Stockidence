from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from . import dagster_client, demo, warehouse

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")

# Re-queue a rating for recompute once the snapshot is this old. Serves the
# existing data immediately (source="refreshing") while the sensor recalcs.
REFRESH_AFTER = timedelta(days=1)


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _stale_snapshot(rating) -> bool:
    """True when the mart snapshot is old enough to warrant a recompute."""
    computed_at = rating.as_of
    if computed_at is None:
        return True
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - computed_at >= REFRESH_AFTER


def get_rating(ticker: str) -> dict:
    """Resolve a ticker to a rating dict.

    Resolution order:
      1. warehouse mart snapshot for the ticker — returned immediately when
         fresh; if stale, a refresh job is launched and the old numbers are
         served with source="refreshing" while it recomputes
      2. no snapshot: launch a refresh job and report source="pending" —
         the UI polls until the mart snapshot lands
      3. deterministic demo data only when the warehouse itself is
         unavailable (no DB), so the UI never hard-fails during build-out

    Push model: compute requests launch the ``refresh_tickers`` Dagster job
    directly (per-ticker cooldown dedups the UI's 10s poll). No sensor polls.
    """
    normalized = normalize_ticker(ticker)
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Invalid ticker: {ticker}")

    # Coverage gate: reject tickers outside the landed symbol universe so
    # a typo can't enqueue a doomed pipeline run. Skipped when the symbol
    # listing isn't available (offline dev / fresh warehouse).
    if warehouse.ticker_exists(normalized) is False:
        raise ValueError(
            f"{normalized} isn't in our coverage universe — "
            "pick one of the suggested symbols."
        )

    rating = warehouse.load_rating_from_warehouse(normalized)
    if rating is not None:
        result = rating.to_dict()
        if _stale_snapshot(rating):
            dagster_client.request_refresh([normalized])
            result["source"] = "refreshing"
        return result

    if not warehouse.is_warehouse_reachable():
        return demo.generate_rating(normalized).to_dict()

    dagster_client.request_refresh([normalized])
    return {
        "ticker": normalized,
        "company_name": "",
        "as_of": "",
        "confidence_score": 0.0,
        "advice": "PENDING",
        "volatility_score": 0.0,
        "categories": [],
        "components": [],
        "buy_plan": None,
        "fair_value": None,
        "target_price": None,
        "source": "pending",
    }