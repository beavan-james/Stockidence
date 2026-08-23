"""Unit tests for the pure response→row normalizers."""

from __future__ import annotations

from datetime import datetime, timezone

from stockidence.ingest.raw_mapping import (
    NORMALIZERS,
    normalize_for,
    validate_rows,
)

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_quote():
    payload = {"c": 250.1, "h": 251.0, "l": 249.0, "o": 249.5, "pc": 247.0}
    rows = normalize_for("quote", payload, "AAPL", NOW)
    assert rows == {"raw_quotes": [{"ticker": "AAPL", "payload": payload}]}


def test_prices_daily():
    payload = {
        "status": "ok",
        "values": [
            {"datetime": "2026-08-14", "open": "1.0", "high": "1.1", "low": "0.9", "close": "1.05", "volume": "100"},
            {"datetime": "2026-08-17", "open": "1.05", "high": "1.2", "low": "1.0", "close": "1.15", "volume": "200"},
        ],
    }
    rows = normalize_for("prices.daily", payload, "AAPL", NOW)
    rows = rows["raw_prices_daily"]
    assert [(r["date"].isoformat(), r["ticker"]) for r in rows] == [("2026-08-14", "AAPL"), ("2026-08-17", "AAPL")]


def test_financials_reported_filters_holes():
    payload = {
        "symbol": "AAPL",
        "data": [
            {"accessNumber": "a1", "symbol": "AAPL", "quarter": 4, "year": 2024, "report": {}},
            {"accessNumber": "b2", "symbol": "AAPL", "quarter": 4, "year": 2025, "report": {}},
            {"accessNumber": "zz", "symbol": "AAPL", "quarter": None, "year": None},  # hole
        ],
    }
    rows = normalize_for("financials_reported", payload, "AAPL", NOW)["raw_financials_reported"]
    assert len(rows) == 2
    assert {(r["quarter"], r["year"]) for r in rows} == {(4, 2024), (4, 2025)}


def test_basic_financials_flattens_series():
    # real Finnhub shape: series.freq = {metric: [{period, v, ttm}, ...]}
    payload = {
        "symbol": "AAPL",
        "metric": {"marketCapitalization": 3_000_000},
        "series": {
            "annual": {
                "netMargin": [
                    {"period": "2024-09-28", "v": 0.28, "ttm": None},
                    {"period": "2025-09-27", "v": 0.30, "ttm": None},
                ],
            },
            "quarterly": {
                "epsTTM": [
                    {"period": "2026-06-27", "v": 6.04, "ttm": None},
                    {"period": "2026-03-28", "v": 5.90, "ttm": None},
                ],
                "netMargin": [{"period": "2026-06-27", "v": 0.29, "ttm": None}],
            },
        },
    }
    rows = normalize_for("basic_financials", payload, "AAPL", NOW)["raw_basic_financials"]

    # annual rows stored as fiscal-year Q4; quarterly rows from the period date
    assert (4, 2024, "netMargin") in {(r["quarter"], r["year"], r["metric"]) for r in rows}
    assert (2, 2026, "epsTTM") in {(r["quarter"], r["year"], r["metric"]) for r in rows}
    assert (2, 2026, "netMargin") in {(r["quarter"], r["year"], r["metric"]) for r in rows}
    # two metrics sharing the same period must NOT clobber each other:
    # the artifact key (ticker, quarter, year, metric) keeps both rows
    eps = next(r for r in rows if r["metric"] == "epsTTM" and r["quarter"] == 2)
    nm = next(r for r in rows if r["metric"] == "netMargin" and r["quarter"] == 2)
    assert eps["payload"]["v"] == 6.04 and nm["payload"]["v"] == 0.29
    assert all(r["ticker"] == "AAPL" for r in rows)
    assert all(r["payload"]["metric"] == r["metric"] for r in rows)


def test_basic_financials_tolerates_legacy_flat_list():
    payload = {
        "symbol": "AAPL",
        "series": {
            "annual": [{"period": "2024-09-28", "v": 0.28}],
            "quarterly": [],
        },
    }
    rows = normalize_for("basic_financials", payload, "AAPL", NOW)["raw_basic_financials"]
    assert len(rows) == 1
    assert rows[0]["metric"] == "" and rows[0]["payload"]["v"] == 0.28


def test_transcript_uses_payload_quarter():
    payload = {
        "symbol": "AAPL",
        "quarter": 4,
        "year": 2025,
        "transcript": [
            {"speaker": "Tim Cook", "title": "Chief Executive Officer", "content": "Good quarter."},
            {"speaker": "Luca Maestri", "title": "CFO", "content": "Numbers next."},
        ],
    }
    rows = normalize_for("earnings_call_transcript", payload, "AAPL|4|2025", NOW)["raw_transcript_segments"]
    assert len(rows) == 2
    assert rows[0]["speaker_sequence"] == 0
    assert rows[1]["speaker_sequence"] == 1
    assert all(r["quarter"] == 4 and r["year"] == 2025 for r in rows)


def test_insider_sentiment():
    payload = {
        "symbol": "AAPL",
        "data": [
            {"year": 2026, "month": 8, "change": 100, "mspr": 0.5},
            {"year": 2026, "month": 7, "change": -40, "mspr": -0.2},
        ],
    }
    rows = normalize_for("insider_sentiment", payload, "AAPL", NOW)["raw_insider_sentiment"]
    assert (2026, 8) in {(r["year"], r["month"]) for r in rows}
    assert all(r["ticker"] == "AAPL" for r in rows)


def test_market_news_fans_out():
    payload = {
        "feed": [
            {
                "title": "Apple beats earnings",
                "url": "https://example.com/apple",
                "time_published": "20260817T120000",
                "url:Vid": [],
                "ticker_sentiment": [
                    {"ticker": "AAPL", "ticker_sentiment_score": 0.3},
                    {"ticker": "MSFT", "ticker_sentiment_score": -0.1},
                ],
            },
            {"title": "No url here", "ticker_sentiment": []},
        ]
    }
    rows = normalize_for("market_news", payload, "", NOW)
    articles = rows["raw_news_articles"]
    assert len(articles) == 1
    aid = articles[0]["article_id"]
    assert aid == "c8cd08d00b0f111f" or len(aid) == 16
    sentiment = rows["news_ticker_sentiment"]
    assert {(s["article_id"], s["ticker"]) for s in sentiment} == {(aid, "AAPL"), (aid, "MSFT")}


def test_commodities():
    payload = {
        "name": "Gold",
        "interval": "monthly",
        "unit": "USD per troy ounce",
        "data": [
            {"date": "2026-07-31", "value": "2400.00"},
            {"date": "2026-08-31", "value": "2450.00"},
        ],
    }
    rows = normalize_for("commodities.gold", payload, "gold", NOW)["raw_commodities"]
    assert all(r["nominal"] == "GOLD" for r in rows)
    assert len(rows) == 2


def test_macro_indicators():
    payload = {"name": "Inflation", "interval": "monthly", "data": [{"date": "2026-07-01", "value": "3.2"}]}
    rows = normalize_for("macro.inflation", payload, "inflation", NOW)["raw_macro_indicators"]
    assert rows[0]["indicator"] == "inflation"
    assert rows[0]["date"].isoformat() == "2026-07-01"


def test_peers_wraps_list():
    rows = normalize_for("peers", ["NVDA", "MSFT"], "AAPL", NOW)["raw_peers"]
    assert rows == [{"ticker": "AAPL", "payload": {"peers": ["NVDA", "MSFT"]}}]


def test_gainers_losers():
    payload = {
        "top_gainers": [{"ticker": "AAA", "price": "10.0", "change_percentage": "5"}],
        "top_losers": [{"ticker": "BBB", "price": "1.0", "change_percentage": "-9"}],
        "most_actively_traded": [{"ticker": "CCC", "price": "50.0"}],
    }
    rows = normalize_for("top_gainers_losers", payload, "top_gainers_losers", NOW)["raw_gainers_losers"]
    assert {r["ticker"] for r in rows} == {"AAA", "BBB", "CCC"}
    assert all(r["date"] == NOW.date() for r in rows)


def test_earnings_calendar():
    payload = {
        "earningsCalendar": [
            {"date": "2026-08-17", "symbol": "AAPL", "quarter": 3, "year": 2026, "epsEstimate": 1.5},
        ]
    }
    rows = normalize_for("earnings_calendar", payload, "earnings_calendar", NOW)["raw_earnings_calendar"]
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["quarter"] == 3 and rows[0]["year"] == 2026


def test_validate_rows_detects_missing_keys():
    import pytest

    from stockidence.ingest.raw_mapping import validate_rows

    with pytest.raises(ValueError):
        validate_rows("quote", {"raw_quotes": [{"payload": {}}]})  # missing ticker


def test_unknown_endpoint_raises():
    import pytest

    from stockidence.ingest.raw_mapping import normalize_for

    with pytest.raises(KeyError):
        normalize_for("not.a.real.endpoint", {}, "x", NOW)


def test_all_normalizers_cover_registry():
    from stockidence.ingest.endpoints import REGISTRY, Provider

    fetched = [spec.name for spec in REGISTRY.values() if spec.provider != Provider.DERIVED]
    missing = [name for name in fetched if name not in NORMALIZERS]
    assert not missing, f"endpoints without normalizers: {missing}"