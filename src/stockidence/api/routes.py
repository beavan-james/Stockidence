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
from pydantic import BaseModel

from ..service import dagster_client, market, ranking, rating_service, sub_scores, warehouse

rating_router = APIRouter(prefix="/api", tags=["rating"])
market_router = APIRouter(prefix="/api", tags=["market"])
meta_router = APIRouter(prefix="/api", tags=["meta"])


class RefreshRequest(BaseModel):
    tickers: list[str]


@rating_router.post("/pipeline/refresh", status_code=202)
def trigger_refresh(body: RefreshRequest) -> dict:
    """Launch the refresh_tickers Dagster job for the given tickers.

    This is the push path the frontend uses instead of the old sensor queue:
    returns the Dagster run id, or 503 when the webserver is unreachable.
    """
    tickers = [t.strip().upper() for t in body.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=422, detail="no tickers to refresh")
    try:
        run_id = dagster_client.submit_refresh_run(tickers)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"run_id": run_id, "tickers": tickers}


@rating_router.get("/rating/{ticker}")
def get_rating(ticker: str) -> dict:
    """Full confidence rating for one ticker (launches a compute if needed)."""
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


@market_router.get("/prices/{ticker}")
def get_price_history(
    ticker: str, months: int = Query(default=12, ge=1, le=120)
) -> list[dict]:
    """Weekly closes, ascending — feeds portfolio holding graphs."""
    return market.get_price_history(ticker, months=months)


@market_router.get("/technicals/{ticker}")
def get_technicals(ticker: str) -> dict | None:
    """Latest raw technical statistics — feeds the ticker profile page."""
    return market.get_technicals(ticker)


@market_router.get("/movers")
def get_movers() -> dict:
    """Top gainers, losers, and most actively traded, with snapshot day."""
    return market.get_market_movers()


@market_router.get("/rankings")
def get_rankings() -> dict:
    """Model ranking cohort for the latest quarter: rank/ticker/sector/score."""
    return ranking.get_rankings()


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
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict:
    """News items, newest first, filtered and paged in SQL.

    `ticker` matches articles whose sentiment_tickers mention it
    (case-insensitive substring, same semantics as the Reflex filter);
    `date_from`/`date_to` bound the publish date (YYYY-MM-DD).
    Only the requested page is parsed — the full table is never loaded.
    Returns an envelope so the client pager needs no total-count guess.
    """
    start = (date_from or "").replace("-", "") or None
    end = (date_to or "").replace("-", "") or None
    return market.get_news_page(
        ticker=ticker, date_from=start, date_to=end, page=page, page_size=page_size
    )


@meta_router.get("/model-weights")
def get_model_weights() -> list[dict]:
    """Confidence blend weights as currently persisted in the mart."""
    return warehouse.get_model_weights()


@meta_router.get("/component-spec")
def get_component_spec() -> dict[str, dict[str, str]]:
    """Sub-score display metadata: label, source fields, direction semantics."""
    return sub_scores.COMPONENT_SPEC
