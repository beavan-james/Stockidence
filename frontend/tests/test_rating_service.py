from __future__ import annotations

from stockidence_app.service import rating_service


def test_valid_ticker_returns_rating():
    rating = rating_service.get_rating("AAPL")
    assert rating["ticker"] == "AAPL"
    assert 0 <= rating["confidence_score"] <= 100
    assert 0 <= rating["volatility_score"] <= 100
    assert len(rating["categories"]) == 4
    assert rating["source"] == "demo"


def test_demo_is_deterministic_in_scores():
    a = rating_service.get_rating("GOOGL")
    b = rating_service.get_rating("GOOGL")
    assert a["confidence_score"] == b["confidence_score"]
    assert a["categories"] == b["categories"]


def test_ticker_normalized_to_upper():
    assert rating_service.get_rating("amzn")["ticker"] == "AMZN"


def test_invalid_ticker_raises():
    import pytest

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


def test_warehouse_fallback_when_db_missing(monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", "/nonexistent/path/to.duckdb")
    rating = rating_service.get_rating("META")
    assert rating["source"] == "demo"