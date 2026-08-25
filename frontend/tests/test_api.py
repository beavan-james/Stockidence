"""Contract tests for the FastAPI layer over the service functions.

Uses TestClient against a seeded warehouse so responses are verified
end-to-end: routing, validation, error mapping, and the news envelope.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import duckdb
import pytest
from fastapi.testclient import TestClient

from stockidence.api.app import app
from stockidence.service import market

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_market_cache():
    """market caches its resolved DB path; re-resolve per test."""
    market._PATH = None
    yield
    market._PATH = None


def _seed_db(tmp_path):
    db = tmp_path / "api.duckdb"
    con = duckdb.connect(str(db))
    for schema in ("mart", "raw"):
        con.execute(f"CREATE SCHEMA {schema}")
    con.execute(
        """
        CREATE TABLE mart.confidence_ratings (
            ticker VARCHAR, company_name VARCHAR, logo VARCHAR,
            as_of TIMESTAMPTZ, confidence_score DOUBLE, advice VARCHAR,
            volatility_score DOUBLE, fair_value DOUBLE, target_price DOUBLE
        )
        """
    )
    fresh = datetime.now(timezone.utc)
    con.execute(
        "INSERT INTO mart.confidence_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["AAPL", "Apple Inc.", None, fresh, 82.0, "STRONG_BUY", 22.0, 245.0, 269.5],
    )
    con.execute(
        "INSERT INTO mart.confidence_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["OLD", "Stale Inc.", None, fresh - timedelta(days=3), 40.0, "HOLD", 50.0, None, None],
    )
    for ddl in (
        """
        CREATE TABLE mart.category_scores (
            ticker VARCHAR, as_of TIMESTAMPTZ, category VARCHAR,
            score DOUBLE, weight DOUBLE
        )
        """,
        """
        CREATE TABLE mart.buy_plans (
            ticker VARCHAR, as_of TIMESTAMPTZ, advised_buy_price DOUBLE,
            stop_loss_price DOUBLE, holding_style VARCHAR
        )
        """,
        """
        CREATE TABLE mart.rating_components (
            ticker VARCHAR, as_of TIMESTAMPTZ, category VARCHAR,
            component VARCHAR, score DOUBLE, weight DOUBLE, source VARCHAR
        )
        """,
    ):
        con.execute(ddl)
    con.execute(
        """
        CREATE TABLE raw.raw_stock_symbols (
            symbol VARCHAR, mic VARCHAR, fetched_at TIMESTAMP, payload JSON
        )
        """
    )
    con.executemany(
        "INSERT INTO raw.raw_stock_symbols VALUES (?, ?, current_timestamp, ?)",
        [
            ["AAPL", "XNAS", json.dumps({"description": "Apple Inc.", "type": "Common Stock"})],
            ["MSFT", "XNAS", json.dumps({"description": "Microsoft Corp.", "type": "Common Stock"})],
            ["OLD", "XNAS", json.dumps({"description": "Stale Inc.", "type": "Common Stock"})],
        ],
    )
    con.execute("CREATE SCHEMA control")
    con.execute(
        """
        CREATE TABLE control.ticker_requests (
            ticker VARCHAR PRIMARY KEY, requested_at TIMESTAMPTZ, status VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE raw.raw_news_articles (
            article_id VARCHAR, source VARCHAR, fetched_at TIMESTAMP, payload JSON
        )
        """
    )
    articles = [
        ("a1", "NVDA climbs again", ["NVDA"], "20260820T120000"),
        ("a2", "NVDA suppliers rally", ["NVDA", "AMD"], "20260819T100000"),
        ("a3", "Yields slip after CPI", [], "20260818T090000"),
    ]
    for i, (aid, title, tickers, ts) in enumerate(articles):
        payload = {
            "title": title,
            "url": f"https://example.com/{aid}",
            "time_published": ts,
            "authors": ["Wire"],
            "summary": title,
            "source": "Example",
            "overall_sentiment_score": 0.1 * (i + 1),
            "overall_sentiment_label": "Bullish",
            "ticker_sentiment": [{"ticker": t, "sentiment_score": "0.2"} for t in tickers],
        }
        con.execute(
            "INSERT INTO raw.raw_news_articles VALUES (?, ?, current_timestamp, ?)",
            [aid, "Example", json.dumps(payload)],
        )
    con.close()
    return db


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rating_served_from_mart(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    response = client.get("/api/rating/AAPL")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["advice"] == "STRONG_BUY"
    assert body["source"] == "warehouse"


def test_rating_stale_snapshot_reports_refreshing(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    body = client.get("/api/rating/OLD").json()
    assert body["source"] == "refreshing"


def test_unknown_ticker_maps_to_404_with_message(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    response = client.get("/api/rating/ZZZZ")
    assert response.status_code == 404
    assert "coverage universe" in response.json()["detail"]


def test_unrated_ticker_queues_and_reports_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    body = client.get("/api/rating/MSFT").json()
    assert body["source"] == "pending"


def test_search_suggestions(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    symbols = [s["symbol"] for s in client.get("/api/search", params={"q": "MS"}).json()]
    assert symbols == ["MSFT"]


def test_news_envelope_filters_and_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    body = client.get("/api/news", params={"ticker": "nvda"}).json()
    assert body["total"] == 2
    assert [i["title"] for i in body["items"]] == ["NVDA climbs again", "NVDA suppliers rally"]
    paged = client.get("/api/news", params={"ticker": "nvda", "page_size": 1, "page": 2}).json()
    assert paged["page_count"] == 2
    assert len(paged["items"]) == 1


def test_model_weights_from_warehouse(tmp_path, monkeypatch):
    db = tmp_path / "weights.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE TABLE mart.model_weights (category VARCHAR, weight DOUBLE)")
    con.execute("INSERT INTO mart.model_weights VALUES ('trend', 0.24), ('valuation', 0.62)")
    con.close()
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))
    weights = client.get("/api/model-weights").json()
    assert weights == [
        {"category": "valuation", "weight": 0.62},
        {"category": "trend", "weight": 0.24},
    ]


def test_component_spec_served(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    spec = client.get("/api/component-spec").json()
    assert spec["macd"]["label"] == "MACD (derived in mart)"
    assert "direction" in spec["rsi"]


def test_quote_absent_returns_null(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(_seed_db(tmp_path)))
    assert client.get("/api/quote/AAPL").json() is None
