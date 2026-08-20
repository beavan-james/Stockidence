from __future__ import annotations

import pytest

from stockidence_app.service import rating_service


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    """Keep every test hermetic: point STOCKIDENCE_DB at nothing so the
    real dev warehouse (and its request queue) is never touched."""
    monkeypatch.setenv("STOCKIDENCE_DB", "/nonexistent/path/to.duckdb")
    yield


def _build_pending_db(tmp_path) -> str:
    """Minimal warehouse: empty mart + a control request queue table."""
    import duckdb
    from datetime import datetime, timezone

    db = tmp_path / "pending.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA mart")
    con.execute("CREATE SCHEMA control")
    con.execute("CREATE TABLE mart.confidence_ratings (ticker VARCHAR)")
    con.execute(
        "CREATE TABLE control.ticker_requests "
        "(ticker VARCHAR NOT NULL, requested_at TIMESTAMPTZ NOT NULL, "
        " status VARCHAR NOT NULL DEFAULT 'pending', PRIMARY KEY (ticker))"
    )
    con.close()
    return str(db)


def test_valid_ticker_returns_rating(monkeypatch):
    rating = rating_service.get_rating("AAPL")
    assert rating["ticker"] == "AAPL"
    assert 0 <= rating["confidence_score"] <= 100
    assert 0 <= rating["volatility_score"] <= 100
    assert len(rating["categories"]) == 4
    assert len(rating["components"]) > 0
    assert rating["source"] == "demo"


def test_demo_is_deterministic_in_scores():
    a = rating_service.get_rating("GOOGL")
    b = rating_service.get_rating("GOOGL")
    assert a["confidence_score"] == b["confidence_score"]
    assert a["categories"] == b["categories"]


def test_ticker_normalized_to_upper():
    assert rating_service.get_rating("amzn")["ticker"] == "AMZN"


def test_invalid_ticker_raises():
    for bad in ("", "BAD TICKER!!", "THIS-IS-WAY-TOO-LONG-XXX"):
        with pytest.raises(ValueError):
            rating_service.get_rating(bad)


def test_buy_plan_only_for_buy_advice():
    advice_values = set()
    for ticker in ("AAPL", "GOOGL", "AMZN", "META", "APP"):
        rating = rating_service.get_rating(ticker)
        advice_values.add(rating["advice"])
        if rating["advice"] in ("STRONG_BUY", "BUY"):
            assert rating["buy_plan"] is not None
        else:
            assert rating["buy_plan"] is None
    assert advice_values  # at least one advice seen


def test_warehouse_row_wins_over_demo(tmp_path, monkeypatch):
    from tests.test_warehouse import _build_warehouse

    monkeypatch.setenv("STOCKIDENCE_DB", str(_build_warehouse(tmp_path)))
    rating = rating_service.get_rating("aapl")
    assert rating["source"] == "warehouse"
    assert rating["advice"] == "STRONG_BUY"


def test_pending_when_warehouse_present_but_unrated(tmp_path, monkeypatch):
    import duckdb

    monkeypatch.setenv("STOCKIDENCE_DB", _build_pending_db(tmp_path))
    rating = rating_service.get_rating("MSFT")
    assert rating["source"] == "pending"
    assert rating["advice"] == "PENDING"

    con = duckdb.connect(str(tmp_path / "pending.duckdb"), read_only=True)
    row = con.execute("SELECT ticker, status FROM control.ticker_requests").fetchone()
    con.close()
    assert row == ("MSFT", "pending")


def test_warehouse_fallback_when_db_missing(monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", "/nonexistent/path/to.duckdb")
    rating = rating_service.get_rating("META")
    assert rating["source"] == "demo"