"""Unit tests for the staleness gate: pure decision logic and the
warehouse-backed conditional checks, exercised against a real (temp-file)
DuckDB warehouse so the SQL paths are actually covered."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from stockidence.ingest.endpoints import get_endpoint
from stockidence.ingest.staleness import (
    FetchDecision,
    StalenessGate,
    check_financials_reported,
    check_insider_sentiment,
    decide,
    latest_expected_period,
)
from stockidence.storage import Watermark, Warehouse

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    return wh


def _wm(fetched_at, high_watermark=None):
    return Watermark("raw.raw_quotes", "AAPL", fetched_at, high_watermark)


def test_decide_derived_never_fetches():
    spec = get_endpoint("technical_indicators")
    assert not decide(spec, None, NOW).should_fetch


def test_decide_never_fetched_fetches():
    assert decide(get_endpoint("quote"), None, NOW).should_fetch


def test_decide_immutable_fetches_once():
    spec = get_endpoint("earnings_call_transcript")
    assert decide(spec, None, NOW).should_fetch
    assert not decide(spec, _wm(NOW - timedelta(days=365)), NOW).should_fetch


def test_decide_ttl_stale_and_fresh():
    spec = get_endpoint("quote")  # ttl 1 min
    stale = _wm(NOW - timedelta(minutes=2))
    assert decide(spec, stale, NOW).should_fetch
    fresh = _wm(NOW - timedelta(seconds=30))
    assert not decide(spec, fresh, NOW).should_fetch


def test_decide_conditional_uses_policy_result():
    spec = get_endpoint("insider_sentiment")  # ttl None, cadence conditional
    wm = _wm(NOW - timedelta(days=90))
    assert decide(spec, wm, NOW, conditional_fetch=True).should_fetch
    assert not decide(spec, wm, NOW, conditional_fetch=False).should_fetch


def test_decide_returns_reason():
    decision = decide(get_endpoint("quote"), _wm(NOW - timedelta(minutes=5)), NOW)
    assert isinstance(decision, FetchDecision)
    assert "ttl" in decision.reason


def test_latest_expected_period():
    assert latest_expected_period(datetime(2026, 2, 15, tzinfo=timezone.utc)) == (2025, 3)
    assert latest_expected_period(datetime(2026, 4, 1, tzinfo=timezone.utc)) == (2025, 4)
    assert latest_expected_period(datetime(2026, 12, 15, tzinfo=timezone.utc)) == (2026, 3)


def test_gate_quote_fresh_vs_stale(warehouse):
    gate = StalenessGate(warehouse, now=NOW)
    assert gate.should_fetch("quote", "AAPL").should_fetch  # never fetched
    warehouse.land("raw_quotes", [{"ticker": "AAPL", "price": 250.0}], fetched_at=NOW)
    assert not gate.should_fetch("quote", "AAPL").should_fetch
    warehouse.land(
        "raw_quotes",
        [{"ticker": "AAPL", "price": 251.0}],
        fetched_at=NOW - timedelta(minutes=2),
    )
    decision = gate.should_fetch("quote", "AAPL", now=NOW)
    assert decision.should_fetch


def test_gate_conditional_insider_sentiment(warehouse):
    gate = StalenessGate(warehouse, now=NOW)
    spec = get_endpoint("insider_sentiment")

    warehouse.land(
        "raw_insider_sentiment",
        [{"ticker": "AAPL", "year": 2026, "month": 7, "change": 50}],
        fetched_at=NOW - timedelta(days=30),
    )
    assert check_insider_sentiment(warehouse, "AAPL", NOW)  # current month absent
    assert gate.should_fetch(spec.name, "AAPL").should_fetch

    warehouse.land(
        "raw_insider_sentiment",
        [{"ticker": "AAPL", "year": 2026, "month": 8, "change": 100}],
        fetched_at=NOW - timedelta(days=5),
    )
    assert not check_insider_sentiment(warehouse, "AAPL", NOW)  # current month present
    assert not gate.should_fetch(spec.name, "AAPL").should_fetch


def test_gate_conditional_financials_reported(warehouse):
    now = datetime(2026, 4, 1, tzinfo=timezone.utc)  # FY2025 Q4 report due by mid-Mar
    gate = StalenessGate(warehouse, now=now)
    spec = get_endpoint("financials_reported")

    warehouse.land(
        "raw_financials_reported",
        [{"ticker": "AAPL", "quarter": 4, "year": 2024, "accessNumber": "a"}],
        fetched_at=now - timedelta(days=400),
    )
    assert check_financials_reported(warehouse, "AAPL", now)  # behind: (2024,4) < (2025,4)
    assert gate.should_fetch(spec.name, "AAPL").should_fetch

    warehouse.land(
        "raw_financials_reported",
        [{"ticker": "AAPL", "quarter": 4, "year": 2025, "accessNumber": "b"}],
        fetched_at=now - timedelta(days=10),
    )
    assert not check_financials_reported(warehouse, "AAPL", now)
    assert not gate.should_fetch(spec.name, "AAPL").should_fetch


def test_gate_conditional_no_watermark_fetches(warehouse):
    gate = StalenessGate(warehouse, now=NOW)
    spec = get_endpoint("insider_sentiment")
    assert gate.should_fetch(spec.name, "MSFT").should_fetch  # no watermark at all


def test_gate_transcript_grain_fallback(warehouse):
    gate = StalenessGate(warehouse, now=NOW)
    spec = get_endpoint("earnings_call_transcript")  # immutable, watermark=(ticker,q,y)
    assert gate.should_fetch(spec.name, "AAPL|4|2025").should_fetch  # no rows at grain

    warehouse.land(
        "raw_transcript_segments",
        [
            {"ticker": "AAPL", "quarter": 4, "year": 2025, "speaker_sequence": 0, "speaker": "CEO"},
            {"ticker": "AAPL", "quarter": 4, "year": 2025, "speaker_sequence": 1, "speaker": "CFO"},
        ],
        fetched_at=NOW - timedelta(days=10),
    )
    assert not gate.should_fetch(spec.name, "AAPL|4|2025").should_fetch  # already have it

    # a different quarter is still not fetched -> should_fetch
    assert gate.should_fetch(spec.name, "AAPL|1|2026").should_fetch
