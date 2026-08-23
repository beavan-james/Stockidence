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
            ticker VARCHAR, company_name VARCHAR, logo VARCHAR,
            as_of TIMESTAMPTZ, confidence_score DOUBLE, advice VARCHAR,
            volatility_score DOUBLE, fair_value DOUBLE, target_price DOUBLE
        )
        """
    )
    con.execute(
        "CREATE TABLE mart.category_scores "
        "(ticker VARCHAR, as_of TIMESTAMPTZ, category VARCHAR, score DOUBLE, weight DOUBLE)"
    )
    con.execute(
        "CREATE TABLE mart.buy_plans "
        "(ticker VARCHAR, as_of TIMESTAMPTZ, advised_buy_price DOUBLE, stop_loss_price DOUBLE, holding_style VARCHAR)"
    )
    con.execute(
        "CREATE TABLE mart.rating_components "
        "(ticker VARCHAR, as_of TIMESTAMPTZ, category VARCHAR, component VARCHAR, score DOUBLE, weight DOUBLE, source VARCHAR)"
    )
    as_of = datetime.now(timezone.utc)
    con.execute(
        "INSERT INTO mart.confidence_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["AAPL", "Apple Inc.", "https://example.com/aapl.png", as_of, 82.0, "STRONG_BUY", 22.0, 245.0, 269.5],
    )
    con.executemany(
        "INSERT INTO mart.category_scores VALUES (?, ?, ?, ?, ?)",
        [
            ["AAPL", as_of, "valuation", 85.0, 0.52],
            ["AAPL", as_of, "trend", 80.0, 0.21],
            ["AAPL", as_of, "moat", 75.0, 0.06],
            ["AAPL", as_of, "sentiment", 85.0, 0.21],
        ],
    )
    con.executemany(
        "INSERT INTO mart.rating_components VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ["AAPL", as_of, "valuation", "discount_to_fair_value", 90.0, 0.40, "live"],
            ["AAPL", as_of, "trend", "price_vs_smas", 70.0, 0.30, "live"],
            ["AAPL", as_of, "trend", "macd", 60.0, 0.20, "live"],
        ],
    )
    con.execute(
        "INSERT INTO mart.buy_plans VALUES (?, ?, ?, ?, ?)",
        ["AAPL", as_of, 230.0, 220.0, "long-term hold"],
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
    assert rating.logo_url == "https://example.com/aapl.png"
    assert len(rating.categories) == 4
    assert rating.buy_plan is not None
    assert rating.buy_plan.advised_buy_price == 230.0
    assert rating.fair_value == 245.0
    assert rating.target_price == 269.5


def test_reads_null_fair_value_as_none(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    con = duckdb.connect(str(db))
    con.execute(
        "UPDATE mart.confidence_ratings SET fair_value = NULL, target_price = NULL"
    )
    con.close()
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))

    rating = warehouse.load_rating_from_warehouse("aapl")
    assert rating is not None
    assert rating.fair_value is None
    assert rating.target_price is None


def test_reads_component_rows_from_mart(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))

    rating = warehouse.load_rating_from_warehouse("AAPL")
    assert rating is not None
    assert len(rating.components) == 3
    by_name = {c.component: c for c in rating.components}
    assert by_name["discount_to_fair_value"].category.value == "valuation"
    assert by_name["price_vs_smas"].score == 70.0
    assert by_name["macd"].weight == 0.20


def test_returns_none_for_unknown_ticker(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))
    assert warehouse.load_rating_from_warehouse("NOPE") is None


def test_parses_pipeline_holding_style_spellings(tmp_path, monkeypatch):
    """Regression: scoring writes 'day trade'/'swing trade'; the strict
    enum lookup used to raise and the blanket except discarded the whole
    rating, so freshly-scored tickers never appeared in the app."""
    db = _build_warehouse(tmp_path)
    con = duckdb.connect(str(db))
    con.execute("UPDATE mart.buy_plans SET holding_style = 'day trade'")
    con.close()
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))

    rating = warehouse.load_rating_from_warehouse("AAPL")
    assert rating is not None
    assert rating.buy_plan.holding_style == "day_trade"


def test_unknown_holding_style_drops_buy_plan_not_rating(tmp_path, monkeypatch):
    db = _build_warehouse(tmp_path)
    con = duckdb.connect(str(db))
    con.execute("UPDATE mart.buy_plans SET holding_style = 'yolo'")
    con.close()
    monkeypatch.setenv("STOCKIDENCE_DB", str(db))

    rating = warehouse.load_rating_from_warehouse("AAPL")
    assert rating is not None
    assert rating.confidence_score == 82.0
    assert rating.buy_plan is None


def test_returns_none_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "nope.duckdb"))
    assert warehouse.load_rating_from_warehouse("AAPL") is None