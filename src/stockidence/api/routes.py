from __future__ import annotations

"""Route handlers: one thin wrapper per service function.

Contracts carried over from the Reflex read path:
  * rating resolution handles pending / refreshing / demo fallbacks inside
    the service; out-of-universe or malformed tickers raise ValueError and
    map to 404 with a user-facing message
  * market getters degrade to deterministic demo data when the warehouse
    has nothing, so empty sections never become HTTP errors
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..service import (
    dagster_client,
    digest,
    market,
    news_summary,
    ranking,
    rating_service,
    sub_scores,
    warehouse,
    weekly,
)
from ..service.rating_service import TICKER_RE, normalize_ticker
from .auth import require_admin

rating_router = APIRouter(prefix="/api", tags=["rating"])
market_router = APIRouter(prefix="/api", tags=["market"])
meta_router = APIRouter(prefix="/api", tags=["meta"])


class RefreshRequest(BaseModel):
    tickers: list[str]


# Bounds what one request can spend, token or not: a backfill of 100
# tickers is 100 of Twelve Data's 800 daily calls.
MAX_REFRESH_TICKERS = 100


def _checked_tickers(raw: list[str], limit: int) -> list[str]:
    """Normalized and deduplicated, refusing an empty or oversized list and
    any ticker outside the landed symbol list (the check a lookup gets,
    skipped when the symbol list can't be read)."""
    tickers = list(dict.fromkeys(normalize_ticker(t) for t in raw if t.strip()))
    if not tickers:
        raise HTTPException(status_code=422, detail="no tickers to refresh")
    if len(tickers) > limit:
        raise HTTPException(
            status_code=422, detail=f"at most {limit} tickers per request, got {len(tickers)}"
        )
    unknown = [t for t in tickers if not TICKER_RE.match(t)]
    unknown += warehouse.tickers_outside_coverage([t for t in tickers if t not in unknown]) or []
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"not in the coverage universe: {', '.join(unknown)}"
        )
    return tickers


@rating_router.post("/pipeline/refresh", status_code=202, dependencies=[Depends(require_admin)])
def trigger_refresh(body: RefreshRequest) -> dict:
    """Launch the refresh_tickers Dagster job for the given tickers.

    Admin route (X-Admin-Token) for bulk runs such as backfills; the site's
    own refreshes start from GET /api/rating/{ticker}. Returns the Dagster
    run id, or 503 when the webserver is unreachable.
    """
    tickers = _checked_tickers(body.tickers, MAX_REFRESH_TICKERS)
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


@market_router.post("/quotes/refresh", status_code=202, dependencies=[Depends(require_admin)])
def trigger_quotes_refresh(body: RefreshRequest) -> dict:
    """Launch the quote-only refresh_quotes Dagster job for the given tickers.

    Admin route (X-Admin-Token): one staleness-gated Finnhub call per
    ticker, no derived rebuilds. Returns the run id; callers poll
    GET /api/quote/{ticker} until `as_of` moves past the request. 503 when
    the Dagster webserver is unreachable.
    """
    tickers = _checked_tickers(body.tickers, dagster_client.MAX_QUOTES_REFRESH)
    try:
        run_id = dagster_client.submit_quotes_run(tickers)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"run_id": run_id, "tickers": tickers}


@market_router.get("/prices/{ticker}")
def get_price_history(ticker: str, months: int = Query(default=12, ge=1, le=120)) -> list[dict]:
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


@market_router.get("/rankings/{ticker}")
def get_ranking_detail(ticker: str) -> dict:
    """One ranked stock: rank context and the per-input score breakdown.

    404 when the ticker isn't in the latest ranking cohort.
    """
    detail = ranking.get_ranking_detail(ticker)
    if detail is None:
        raise HTTPException(
            status_code=404, detail=f"{ticker.upper()} is not in the latest ranking"
        )
    return detail


@market_router.get("/weekly")
def get_weekly() -> dict:
    """Stocks of the Week: this week's ranked list with rank changes, last
    week's top 10 and how they did, and the walk-forward backtest."""
    return weekly.get_weekly()


@market_router.get("/model/overview")
def get_model_overview() -> dict:
    """Cohort-wide input weights and the quarterly track record."""
    return ranking.get_model_overview()


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
    q: str = Query(default="", max_length=200),
    date_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> dict:
    """News items, newest first, filtered and paged in SQL.

    `q` searches headlines: every whitespace-separated word must appear
    in the title (case-insensitive, any order);
    `date_from`/`date_to` bound the publish date (YYYY-MM-DD).
    Only the requested page is parsed — the full table is never loaded.
    Returns an envelope so the client pager needs no total-count guess.
    """
    start = (date_from or "").replace("-", "") or None
    end = (date_to or "").replace("-", "") or None
    return market.get_news_page(q=q, date_from=start, date_to=end, page=page, page_size=page_size)


@market_router.get("/digest/{period}")
def get_digest(
    period: Literal["daily", "weekly"],
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    """One weekday's or one week's news digest (the latest when `date` is
    omitted; a week is dated by its Friday): the top stories, what each
    score input gave them, and the other articles grouped under each. 404
    for a date with no digest."""
    from datetime import date as _date

    try:
        day = _date.fromisoformat(date) if date else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"not a date: {date}") from exc
    result = digest.get_digest(period, day)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no {period} digest for {date}")
    return result


@market_router.get("/summary/{period}")
def get_summary(
    period: Literal["daily", "weekly"],
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    """The model-written news summary: the latest written one on or before
    `date` (a week is dated by its Friday), or the latest of all when `date`
    is omitted. The daily paragraph, or the weekly article as part 0 the
    overview and parts 1..n its sections. Each part lists its sources
    (headline, outlet, link); a part whose text failed the checks has status
    `sources_only` and no body. `previous_date`/`next_date` step through
    written digests. Empty `parts` when there is none."""
    from datetime import date as _date

    try:
        day = _date.fromisoformat(date) if date else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"not a date: {date}") from exc
    return news_summary.get_summary(period, day)


@meta_router.get("/model-weights")
def get_model_weights() -> list[dict]:
    """Confidence blend weights as currently persisted in the mart."""
    return warehouse.get_model_weights()


@meta_router.get("/component-spec")
def get_component_spec() -> dict[str, dict[str, str]]:
    """Sub-score display metadata: label, source fields, direction semantics."""
    return sub_scores.COMPONENT_SPEC
