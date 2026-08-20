"""Integration tests for the ingestion engine against fake clients and a
real temp-file DuckDB. Verifies gate behavior, call-shaped kwargs, row
landing, and watermark upkeep — no network or API keys involved."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from stockidence.ingest.endpoints import Provider
from stockidence.ingest.engine import IngestEngine
from stockidence.storage import Warehouse

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

QUOTE = {"c": 250.1, "h": 251.0, "l": 249.0, "o": 249.5, "pc": 247.0}
PRICES = {
    "status": "ok",
    "values": [
        {"datetime": "2026-08-14", "open": "1.0", "high": "1.1", "low": "0.9", "close": "1.05", "volume": "100"},
        {"datetime": "2026-08-17", "open": "1.05", "high": "1.2", "low": "1.0", "close": "1.15", "volume": "200"},
    ],
}
MACRO = {"name": "Inflation", "interval": "monthly", "data": [{"date": "2026-07-01", "value": "3.2"}]}
FINANCIALS = {
    "symbol": "AAPL",
    "data": [
        {"accessNumber": "a1", "symbol": "AAPL", "quarter": 4, "year": 2024, "report": {}},
        {"accessNumber": "b2", "symbol": "AAPL", "quarter": 4, "year": 2025, "report": {}},
    ],
}
SENTIMENT = {
    "symbol": "AAPL",
    "data": [{"year": 2026, "month": 7, "change": 100, "mspr": 0.5}],
}
TRANSCRIPT = {
    "symbol": "AAPL",
    "quarter": 4,
    "year": 2025,
    "transcript": [{"speaker": "CEO", "title": "CEO", "content": "hi"}, {"speaker": "CFO", "title": "CFO", "content": "hey"}],
}
NEWS = {
    "feed": [
        {
            "title": "Apple beats earnings",
            "url": "https://example.com/a",
            "ticker_sentiment": [{"ticker": "AAPL", "ticker_sentiment_score": 0.2}],
        }
    ]
}
IPO_CAL = {"ipoCalendar": [{"date": "2026-08-20", "symbol": "XYZ", "status": "expected"}]}


class FakeFinnhub:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    def _h(self, name):
        def handler(**kwargs):
            self.calls.append((name, kwargs))
            return self.responses[name]

        return handler

    def quote(self, **kwargs):
        return self._h("quote")(**kwargs)

    def financials_reported(self, **kwargs):
        return self._h("financials_reported")(**kwargs)

    def insider_sentiment(self, **kwargs):
        return self._h("insider_sentiment")(**kwargs)

    def ipo_calendar(self, **kwargs):
        self.calls.append(("ipo_calendar", kwargs))
        if kwargs.get("from_date") == "2026-01-01":
            return {"ipoCalendar": []}
        return self.responses["ipo_calendar"]


class FakeTwelveData:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def time_series(self, **kwargs):
        self.calls.append(("time_series", kwargs))
        return PRICES


class FakeAlphaVantage:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def inflation(self, **kwargs):
        self.calls.append(("inflation", kwargs))
        return MACRO

    def market_news(self, **kwargs):
        self.calls.append(("market_news", kwargs))
        return NEWS

    def earnings_call_transcript(self, **kwargs):
        self.calls.append(("earnings_call_transcript", kwargs))
        return TRANSCRIPT


@pytest.fixture
def engine(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    clients = {
        Provider.FINNHUB: FakeFinnhub(
            responses={
                "quote": QUOTE,
                "financials_reported": FINANCIALS,
                "insider_sentiment": SENTIMENT,
                "ipo_calendar": IPO_CAL,
            }
        ),
        Provider.TWELVE_DATA: FakeTwelveData(),
        Provider.ALPHA_VANTAGE: FakeAlphaVantage(),
    }
    return wh, IngestEngine(wh, clients=clients)


def test_quote_fetches_once_then_caches(engine):
    wh, eng = engine
    fh = eng.clients[Provider.FINNHUB]

    first = eng.ingest_on_demand("quote", "AAPL", now=NOW)
    assert first.fetched and first.rows_written == 1

    cached = eng.ingest_on_demand("quote", "AAPL", now=NOW)
    assert not cached.fetched
    assert "fresh" in cached.reason

    eng.ingest_on_demand("quote", "AAPL", now=NOW, force=True)
    assert fh.calls.count(("quote", {"symbol": "AAPL"})) == 2


def test_prices_daily_incremental_start_date(engine):
    wh, eng = engine
    td = eng.clients[Provider.TWELVE_DATA]

    first = eng.ingest_on_demand("prices.daily", "AAPL", now=NOW)
    assert first.fetched and first.rows_written == 2
    assert first.high_watermark == "2026-08-17"
    assert td.calls[0] == ("time_series", {"symbol": "AAPL"})

    # TTL is 1 day; same-day request reuses the cache instead of re-calling
    result = eng.ingest_on_demand("prices.daily", "AAPL", now=NOW)
    assert not result.fetched
    assert len(td.calls) == 1

    # A forced refetch goes incremental, starting from the tracked high watermark
    eng.ingest_on_demand("prices.daily", "AAPL", now=NOW, force=True)
    assert td.calls[1] == ("time_series", {"symbol": "AAPL", "start_date": "2026-08-17"})


def test_financials_reported_on_demand(engine):
    wh, eng = engine
    fh = eng.clients[Provider.FINNHUB]
    result = eng.ingest_on_demand("financials_reported", "AAPL", now=NOW)
    assert result.fetched and result.rows_written == 2
    assert fh.calls[-1] == ("financials_reported", {"symbol": "AAPL", "freq": "annual"})


def test_insider_sentiment_year_window(engine):
    wh, eng = engine
    fh = eng.clients[Provider.FINNHUB]
    eng.ingest_on_demand("insider_sentiment", "AAPL", now=NOW)
    kwargs = fh.calls[-1][1]
    assert kwargs["from_date"] == "2026-01-01"
    assert kwargs["to_date"] == "2026-08-17"
    # July row exists but current month (August) has none -> still refetch
    result = eng.ingest_on_demand("insider_sentiment", "AAPL", now=NOW)
    assert result.fetched


def test_transcript_quarter_dimension(engine):
    wh, eng = engine
    av = eng.clients[Provider.ALPHA_VANTAGE]
    result = eng.ingest_on_demand("earnings_call_transcript", "AAPL|4|2025", now=NOW)
    assert result.fetched and result.rows_written == 2
    assert av.calls[-1] == ("earnings_call_transcript", {"symbol": "AAPL", "quarter": "2025Q4"})

    # immutable: same grain must not re-fetch; a different quarter must
    result2 = eng.ingest_on_demand("earnings_call_transcript", "AAPL|4|2025", now=NOW)
    assert not result2.fetched
    result3 = eng.ingest_on_demand("earnings_call_transcript", "AAPL|1|2025", now=NOW)
    assert result3.fetched


def test_scheduled_macro_lands_rows(engine):
    wh, eng = engine
    result = eng.ingest_scheduled("macro.inflation", now=NOW)
    assert result.fetched and result.rows_written == 1
    rows = wh.connect(read_only=True).execute("SELECT indicator, date FROM raw.raw_macro_indicators").fetchall()
    assert rows == [("inflation", date(2026, 7, 1))]


def test_scheduled_calendar_uses_default_window(engine):
    wh, eng = engine
    fh = eng.clients[Provider.FINNHUB]
    result = eng.ingest_scheduled("ipo_calendar", now=NOW)
    assert result.fetched and result.rows_written == 1
    kwargs = fh.calls[-1][1]
    assert kwargs["from_date"] == "2026-08-17"
    assert kwargs["to_date"] == "2026-10-01"  # today + 45 days

    result2 = eng.ingest_scheduled("ipo_calendar", now=NOW, params={"from_date": "2026-01-01", "to_date": "2026-02-01"})
    assert result2.fetched and result2.rows_written == 0  # no IPOs inside the custom window


def test_market_news_fanout_lands_both_tables(engine):
    wh, eng = engine
    result = eng.ingest_scheduled("market_news", now=NOW)
    assert result.fetched
    con = wh.connect(read_only=True)
    assert con.execute("SELECT COUNT(*) FROM raw.raw_news_articles").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM raw.news_ticker_sentiment").fetchone()[0] == 1


def test_unknown_endpoint_raises(engine):
    wh, eng = engine
    with pytest.raises(KeyError):
        eng.ingest_on_demand("not.real", "AAPL", now=NOW)