from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from stockidence_app.service import warehouse


def _build_warehouse(tmp_path):
    db = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA mart")
    con.execute(
        """
        CREATE TABLE mart.confidence_ratings (
            ticker VARCHAR, company_name VARCHAR, as_of TIMESTAMPTZ,
            confidence_score DOUBLE, advice VARCHAR, volatility_score DOUBLE
        )
        """
    )
    con.execute(
        "CREATE TABLE mart.rating_components "
        "(ticker VARCHAR, as_of TIMESTAMPTZ, category VARCHAR, score DOUBLE, weight DOUBLE)"
    )
    con.execute(
        "CREATE TABLE mart.buy_plans "
        "(ticker VARCHAR, as_of TIMESTAMPTZ, advised_buy_price DOUBLE, stop_loss_price DOUBLE, holding_style VARCHAR)"
    )
    as_of = datetime.now(timezone.utc)
    con.execute(
        "INSERT INTO mart.confidence_ratings VALUES (?, ?, ?, ?, ?, ?)",
        ["AAPL", "Apple Inc.", as_of, 82.0, "STRONG_BUY", 22.0],
    )
    con.executemany(
        "INSERT INTO mart.rating_components VALUES (?, ?, ?, ?, ?)",
        [
            ["AAPL", as_of, "valuation", 85.0, 0.4],
            ["AAPL", as_of, "trend", 80.0, 0.25],
            ["AAPL", as_of, "momentum", 75.0, 0.15],
            ["AAPL", as_of, "sentiment", 85.0, 0.2],
        ],
    )
    con.execute(
        "INSERT INTO mart.buy_plans VALUES (?, ?, ?, ?, ?)",
        ["AAPL", as_of, 230.0, 220.0, "long_term_hold"],
    )
    con.close()
    return db


def test_reads_rating_from_mart(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))

    rating = warehouse.load_rating_from_warehouse("aapl")
    assert rating is not None
    assert rating.source == "warehouse"
    assert rating.advice == "STRONG_BUY"
    assert rating.confidence_score == 82.0
    assert len(rating.categories) == 4
    assert rating.buy_plan is not None
    assert rating.buy_plan.advised_buy_price == 230.0


def test_returns_none_for_unknown_ticker(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))
    assert warehouse.load_rating_from_warehouse("NOPE") is None


def test_returns_none_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "nope.duckdb"))
    assert warehouse.load_rating_from_warehouse("AAPL") is None