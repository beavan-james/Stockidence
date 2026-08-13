from __future__ import annotations

import re

from . import demo, warehouse

TICKER_RE = re.compile(r"^[A-Z0-9.\-^]{1,10}$")


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def get_rating(ticker: str) -> dict:
    """Resolve a ticker to a rating dict, preferring the warehouse mart.

    Falls back to deterministic demo data when the warehouse has nothing for
    the ticker so the UI stays fully functional during pipeline build-out.
    """
    normalized = normalize_ticker(ticker)
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Invalid ticker: {ticker}")

    rating = warehouse.load_rating_from_warehouse(normalized)
    if rating is None:
        rating = demo.generate_rating(normalized)
    return rating.to_dict()