"""Tests for the ticker request queue: warehouse lifecycle + the sensor's
partition-staging helper against an ephemeral Dagster instance."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from dagster import DagsterInstance

from stockidence.storage import Warehouse

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


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


def test_stage_ticker_runs_adds_partitions_and_marks_launched(warehouse):
    from stockidence.definitions import stage_ticker_runs

    instance = DagsterInstance.ephemeral()
    warehouse.request_ticker("AAPL", requested_at=NOW)
    warehouse.request_ticker("NVDA", requested_at=NOW)

    staged = stage_ticker_runs(warehouse, instance)
    assert staged == ["AAPL", "NVDA"]
    assert set(instance.get_dynamic_partitions("ticker")) == {"AAPL", "NVDA"}

    # queue consumed; a second stage is a no-op
    assert stage_ticker_runs(warehouse, instance) == []
    assert set(instance.get_dynamic_partitions("ticker")) == {"AAPL", "NVDA"}


def test_stage_after_re_request_adds_new_partition_only(warehouse):
    from stockidence.definitions import stage_ticker_runs

    instance = DagsterInstance.ephemeral()
    warehouse.request_ticker("AAPL", requested_at=NOW)
    stage_ticker_runs(warehouse, instance)

    # AAPL re-requested: partition already exists, staging still queues a run
    warehouse.request_ticker("AAPL", requested_at=NOW)
    assert stage_ticker_runs(warehouse, instance) == ["AAPL"]
    assert instance.get_dynamic_partitions("ticker") == ["AAPL"]


def test_sensor_registered_in_definitions():
    from stockidence.definitions import defs

    sensor_names = {s.name for s in defs.sensors}
    assert "ticker_request_sensor" in sensor_names