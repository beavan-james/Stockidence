from __future__ import annotations

import re

from . import demo, warehouse

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def get_rating(ticker: str) -> dict:
    """Resolve a ticker to a rating dict.

    Resolution order:
      1. warehouse mart snapshot for the ticker (source="warehouse")
      2. queue a pipeline request and report source="pending" — the Dagster
         sensor consumes control.ticker_requests and will compute the ticker
      3. deterministic demo data only when the warehouse itself is
         unavailable (no DB), so the UI never hard-fails during build-out
    """
    normalized = normalize_ticker(ticker)
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Invalid ticker: {ticker}")

    rating = warehouse.load_rating_from_warehouse(normalized)
    if rating is not None:
        return rating.to_dict()

    if warehouse.enqueue_ticker_request(normalized) is True:
        return {
            "ticker": normalized,
            "company_name": "",
            "as_of": "",
            "confidence_score": 0.0,
            "advice": "PENDING",
            "volatility_score": 0.0,
            "categories": [],
            "buy_plan": None,
            "source": "pending",
        }

    rating = demo.generate_rating(normalized)
    return rating.to_dict()