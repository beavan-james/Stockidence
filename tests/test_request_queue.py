"""Tests for the ticker request queue lifecycle plus the push-model launch
path (no sensors): cooldown dedup and launch failure mapping."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stockidence.storage import Warehouse

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    return wh


def test_request_pending_mark_lifecycle(warehouse):
    warehouse.request_ticker("AAPL", requested_at=NOW)
    warehouse.request_ticker("MSFT", requested_at=NOW)

    assert warehouse.pending_ticker_requests() == ["AAPL", "MSFT"]

    warehouse.mark_ticker_requests_launched(["AAPL"])
    assert warehouse.pending_ticker_requests() == ["MSFT"]

    # re-request of an already-launched ticker flips it back to pending
    warehouse.request_ticker("AAPL", requested_at=NOW)
    assert warehouse.pending_ticker_requests() == ["AAPL", "MSFT"]


def test_mark_empty_is_noop(warehouse):
    warehouse.mark_ticker_requests_launched([])  # must not raise


def test_no_sensors_registered_push_model():
    from stockidence.definitions import defs

    assert list(defs.sensors or []) == []


def test_launch_cooldown_skips_recent_tickers(monkeypatch):
    import time

    from stockidence.service import dagster_client

    monkeypatch.setitem(dagster_client._last_launch, "AAPL", time.monotonic())
    # No network touched: cooldown short-circuits before any launch attempt.
    assert dagster_client.request_refresh(["AAPL"]) is None


def test_submit_raises_when_webserver_unreachable(monkeypatch):
    monkeypatch.setenv("DAGSTER_WEB_URL", "http://localhost:9")

    from stockidence.service import dagster_client

    with pytest.raises(RuntimeError):
        dagster_client.submit_refresh_run(["AAPL"])