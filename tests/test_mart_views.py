"""Contract tests for the mart presentation views the frontend reads.

The m_* tables are storage; the unprefixed objects (confidence_ratings,
category_scores, buy_plans) are views that map storage columns to the
read API contract. Both sides have drifted before (holding_style
spellings, advice casing), so the exact strings are pinned here.
"""

from __future__ import annotations

from stockidence.mart.scoring import CONFIDENCE_WEIGHTS
from stockidence.storage import Warehouse


def _seeded(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    con = wh.connect()
    con.execute(
        """
        INSERT INTO mart.m_confidence_ratings
            (ticker, computed_at, rating, confidence_score, volatility_score,
             valuation_score, trend_score, sentiment_score, moat_score)
        VALUES ('AAPL', '2026-08-20 12:00:00+00', 'Strong Buy', 67.0, 30.0,
                70.0, 60.0, 50.0, 40.0)
        """
    )
    return wh, con


def test_view_maps_rating_to_advice_contract(tmp_path):
    """Ratings are stored 'Strong Buy'; the read API is UPPER_SNAKE."""
    wh, con = _seeded(tmp_path)
    row = con.execute(
        "SELECT ticker, advice FROM mart.confidence_ratings WHERE ticker='AAPL'"
    ).fetchone()
    assert row == ("AAPL", "STRONG_BUY")
    con.close()


def test_model_weights_match_scoring_spec(tmp_path):
    """init_schema seeds model_weights from CONFIDENCE_WEIGHTS — the table
    must never drift from the weights the scorer actually applies."""
    wh = Warehouse(tmp_path / "w.duckdb")
    wh.init_schema()
    con = wh.connect()
    stored = dict(con.execute("SELECT category, weight FROM mart.model_weights").fetchall())
    assert stored == CONFIDENCE_WEIGHTS
    con.close()
