"""Pure API-response → raw-row mappers for every registry endpoint.

Each normalizer is a pure function `(payload, dimension_key) -> {artifact: rows}`
where rows are dicts ready for `Warehouse.land` — key columns typed (str/date/int)
plus the original response fragment as `payload`. One response can fan out to
several artifact tables (e.g. market_news → articles + ticker sentiment).

Design rules:
  - No I/O, no clock: `now` is passed in when a row needs it (gainers/losers).
  - Layers stay explicit: this module only shapes rows for the raw layer.
  - Unknown endpoints raise KeyError instead of silently dropping data.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Callable

from .storage import RAW_SCHEMA


def _as_date(value: str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _quarter_of(period: str) -> int:
    return (date.fromisoformat(period).month - 1) // 3 + 1


def _article_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


Normalizer = Callable[[dict[str, Any], str, datetime], dict[str, list[dict[str, Any]]]]


def _single(artifact: str, rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {artifact: rows}


def normalize_quote(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Finnhub /quote: one ticker row, payload kept whole."""
    return _single("raw_quotes", [{"ticker": symbol, "payload": payload}])


def normalize_prices_daily(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Twelve Data /time_series: one row per bar, keyed (ticker, date)."""
    rows = [
        {"ticker": symbol, "date": _as_date(bar["datetime"]), "payload": bar}
        for bar in payload.get("values", [])
        if bar.get("datetime")
    ]
    return _single("raw_prices_daily", rows)


def normalize_company_profile2(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    ticker = payload.get("ticker") or symbol
    return _single("raw_company_profile", [{"ticker": ticker, "payload": payload}])


def normalize_basic_financials(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Finnhub /stock/metrics: flatten the annual + quarterly series.

    Metric entries arrive keyed by period string; annual rows are stored as
    the fiscal year's Q4 since the artifact key is (ticker, quarter, year).
    """
    ticker = payload.get("symbol") or symbol
    rows: list[dict[str, Any]] = []
    for freq, quarter in (("annual", 4), ("quarterly", None)):
        series = (payload.get("series") or {}).get(freq) or []
        for entry in series:
            period = entry.get("period")
            if not period:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "quarter": quarter if quarter is not None else _quarter_of(period),
                    "year": _as_date(period).year,
                    "payload": {**entry, "freq": freq},
                }
            )
    return _single("raw_basic_financials", rows)


def normalize_financials_reported(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Finnhub /stock/financials-reported: one row per filing report."""
    ticker = payload.get("symbol") or symbol
    rows = [
        {
            "ticker": entry.get("symbol") or ticker,
            "quarter": entry["quarter"],
            "year": entry["year"],
            "payload": entry,
        }
        for entry in payload.get("data", [])
        if entry.get("quarter") is not None and entry.get("year") is not None
    ]
    return _single("raw_financials_reported", rows)


def normalize_eps_surprises(payload: list[dict[str, Any]], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {
            "ticker": entry.get("symbol") or symbol,
            "quarter": entry["quarter"],
            "year": entry["year"],
            "payload": entry,
        }
        for entry in payload
        if entry.get("quarter") is not None and entry.get("year") is not None
    ]
    return _single("raw_eps_surprises", rows)


def normalize_earnings_call_transcript(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Alpha Vantage EARNINGS_CALL_TRANSCRIPT: one row per speaker segment.

    AV returns entries chronologically; speaker_sequence is their index in the
    response, giving the artifact its (ticker, quarter, year, sequence) key.
    """
    ticker = payload.get("symbol") or symbol
    quarter = payload.get("quarter")
    year = payload.get("year")
    if quarter is None or year is None:
        dims = symbol.split("|")
        if len(dims) >= 3:
            ticker, quarter, year = dims[0], int(dims[1]), int(dims[2])
        else:
            raise ValueError(f"earnings_call_transcript: missing quarter/year in payload or dimension")
    rows = [
        {
            "ticker": ticker,
            "quarter": quarter,
            "year": year,
            "speaker_sequence": i,
            "payload": entry,
        }
        for i, entry in enumerate(payload.get("transcript", []))
    ]
    return _single("raw_transcript_segments", rows)


def normalize_insider_sentiment(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    ticker = payload.get("symbol") or symbol
    rows = [
        {"ticker": entry.get("symbol") or ticker, "year": entry["year"], "month": entry["month"], "payload": entry}
        for entry in payload.get("data", [])
        if entry.get("year") is not None and entry.get("month") is not None
    ]
    return _single("raw_insider_sentiment", rows)


def normalize_recommendation_trends(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    ticker = payload.get("symbol") or symbol
    rows = [
        {"ticker": ticker, "period": _as_date(entry["period"]), "payload": entry}
        for entry in payload.get("data", [])
        if entry.get("period")
    ]
    return _single("raw_recommendation_trends", rows)


def normalize_peers(payload: list[str], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    return _single("raw_peers", [{"ticker": symbol, "payload": {"peers": payload}}])


def _macro_name(indicator: str) -> Callable[[dict[str, Any], str, datetime], dict[str, list[dict[str, Any]]]]:
    def normalize(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
        rows = [
            {"indicator": indicator, "date": _as_date(entry["date"]), "payload": entry}
            for entry in payload.get("data", [])
            if entry.get("date")
        ]
        return _single("raw_macro_indicators", rows)

    return normalize


def _commodity_name(nominal: str) -> Callable[[dict[str, Any], str, datetime], dict[str, list[dict[str, Any]]]]:
    def normalize(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
        rows = [
            {"nominal": nominal, "date": _as_date(entry["date"]), "payload": entry}
            for entry in payload.get("data", [])
            if entry.get("date")
        ]
        return _single("raw_commodities", rows)

    return normalize


def normalize_stock_symbols(payload: list[dict[str, Any]], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {"mic": entry.get("mic", ""), "symbol": entry["symbol"], "payload": entry}
        for entry in payload
        if entry.get("symbol") is not None
    ]
    return _single("raw_stock_symbols", rows)


def normalize_gainers_losers(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Alpha Vantage TOP_GAINERS_LOSERS: one row per mover entry.

    A ticker can appear in more than one bucket the same day; rows upsert on
    (ticker, date) so the last bucket written wins — acceptable for a
    post-close snapshot table.
    """
    day = now.date()
    rows = [
        {"ticker": entry["ticker"], "date": day, "payload": {**entry, "bucket": bucket}}
        for bucket in ("top_gainers", "top_losers", "top_most_active")
        for entry in payload.get(bucket, [])
        if entry.get("ticker")
    ]
    return _single("raw_gainers_losers", rows)


def normalize_ipo_calendar(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {"symbol": entry["symbol"], "date": _as_date(entry["date"]), "payload": entry}
        for entry in payload.get("ipoCalendar", [])
        if entry.get("symbol") and entry.get("date")
    ]
    return _single("raw_ipo_calendar", rows)


def normalize_earnings_calendar(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {"symbol": entry["symbol"], "quarter": entry["quarter"], "year": entry["year"], "payload": entry}
        for entry in payload.get("earningsCalendar", [])
        if entry.get("symbol") and entry.get("quarter") is not None and entry.get("year") is not None
    ]
    return _single("raw_earnings_calendar", rows)


def normalize_market_news(payload: dict[str, Any], symbol: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Alpha Vantage NEWS_SENTIMENT: fan out to articles + ticker sentiment."""
    articles: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []
    for item in payload.get("feed", []):
        url = item.get("url")
        if not url:
            continue
        article_id = _article_id(url)
        articles.append({"article_id": article_id, "payload": item})
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker"):
                ticker_rows.append(
                    {"article_id": article_id, "ticker": ts["ticker"], "payload": ts}
                )
    return {"raw_news_articles": articles, "news_ticker_sentiment": ticker_rows}


NORMALIZERS: dict[str, Normalizer] = {
    "quote": normalize_quote,
    "prices.daily": normalize_prices_daily,
    "company_profile2": normalize_company_profile2,
    "basic_financials": normalize_basic_financials,
    "financials_reported": normalize_financials_reported,
    "eps_surprises": normalize_eps_surprises,
    "earnings_call_transcript": normalize_earnings_call_transcript,
    "insider_sentiment": normalize_insider_sentiment,
    "recommendation_trends": normalize_recommendation_trends,
    "peers": normalize_peers,
    "commodities.gold": _commodity_name("GOLD"),
    "commodities.silver": _commodity_name("SILVER"),
    "macro.inflation": _macro_name("inflation"),
    "macro.cpi": _macro_name("cpi"),
    "macro.unemployment": _macro_name("unemployment"),
    "macro.federal_funds_rate": _macro_name("federal_funds_rate"),
    "macro.natural_gas": _macro_name("natural_gas"),
    "macro.real_gdp_per_capita": _macro_name("real_gdp_per_capita"),
    "stock_symbols": normalize_stock_symbols,
    "top_gainers_losers": normalize_gainers_losers,
    "ipo_calendar": normalize_ipo_calendar,
    "earnings_calendar": normalize_earnings_calendar,
    "market_news": normalize_market_news,
}


def normalize_for(endpoint: str, payload: Any, dimension_key: str, now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Normalize a raw response into artifact rows for one endpoint."""
    try:
        normalizer = NORMALIZERS[endpoint]
    except KeyError:
        raise KeyError(f"no normalizer registered for endpoint: {endpoint}")
    return normalizer(payload, dimension_key, now)


def validate_rows(endpoint: str, rows: dict[str, list[dict[str, Any]]]) -> None:
    """Check every row carries the artifact table's key columns."""
    for artifact, artifact_rows in rows.items():
        keys = {name for name, _ in RAW_SCHEMA[artifact]}
        for row in artifact_rows:
            missing = keys - row.keys()
            if missing:
                raise ValueError(f"{endpoint} → {artifact}: rows missing key columns {sorted(missing)}")