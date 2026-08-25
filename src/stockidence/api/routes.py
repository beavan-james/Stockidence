from __future__ import annotations

"""Route handlers: one thin wrapper per service function.

Contracts carried over from the Reflex read path:
  * rating resolution handles pending / refreshing / demo fallbacks inside
    the service; out-of-universe or malformed tickers raise ValueError and
    map to 404 with a user-facing message
  * market getters degrade to deterministic demo data when the warehouse
    has nothing, so empty sections never become HTTP errors
"""

from fastapi import APIRouter, HTTPException, Query

from ..service import market, rating_service, sub_scores, warehouse

rating_router = APIRouter(prefix="/api", tags=["rating"])
market_router = APIRouter(prefix="/api", tags=["market"])
meta_router = APIRouter(prefix="/api", tags=["meta"])


@rating_router.get("/rating/{ticker}")
def get_rating(ticker: str) -> dict:
    """Full confidence rating for one ticker (queues a compute if needed)."""
    try:
        return rating_service.get_rating(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@rating_router.get("/search")
def search_tickers(
    q: str = Query(min_length=1),
    limit: int = Query(default=8, ge=1, le=25),
) -> list[dict]:
    """Autocomplete over the landed US symbol universe."""
    return warehouse.search_tickers(q, limit=limit)


@market_router.get("/quote/{ticker}")
def get_quote(ticker: str) -> dict | None:
    """Latest cached quote for the profile header badge; null when absent."""
    return market.get_quote(ticker)


@market_router.get("/movers")
def get_movers() -> dict:
    """Top gainers, losers, and most actively traded, with snapshot day."""
    return market.get_market_movers()


@market_router.get("/calendar/ipos")
def get_ipo_calendar(limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    return market.get_ipo_calendar(limit)


@market_router.get("/calendar/earnings")
def get_earnings_calendar(limit: int = Query(default=10, ge=1, le=50)) -> list[dict]:
    return market.get_earnings_calendar(limit)


@market_router.get("/macro")
def get_macro_metrics() -> list[dict]:
    """Latest macro indicator cards with sparkline series."""
    return market.get_macro_metrics()


@market_router.get("/commodities")
def get_commodities() -> list[dict]:
    return market.get_commodities()


@market_router.get("/news")
def get_news(
    ticker: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """News items, newest first, filtered and paged server-side.

    `ticker` matches articles whose sentiment_tickers mention it
    (case-insensitive substring, same semantics as the Reflex filter).
    Returns an envelope so the client pager needs no total-count guess.
    """
    news = market.get_market_news()
    query = ticker.strip().upper()
    if query:
        news = [n for n in news if query in (n.get("sentiment_tickers") or "").upper()]
    start = (page - 1) * page_size
    items = news[start : start + page_size]
    return {
        "items": items,
        "total": len(news),
        "page": page,
        "page_size": page_size,
        "page_count": max(1, -(-len(news) // page_size)),
    }


@meta_router.get("/model-weights")
def get_model_weights() -> list[dict]:
    """Confidence blend weights as currently persisted in the mart."""
    return warehouse.get_model_weights()


@meta_router.get("/component-spec")
def get_component_spec() -> dict[str, dict[str, str]]:
    """Sub-score display metadata: label, source fields, direction semantics."""
    return sub_scores.COMPONENT_SPEC
