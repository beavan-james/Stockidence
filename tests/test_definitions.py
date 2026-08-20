"""Unit tests for the Dagster definitions layer.

The ticker_data asset runs with a fake engine resource (no API keys, no
network); scheduled jobs are verified against the registry composition."""

from __future__ import annotations

import pytest
from dagster import DagsterInstance, materialize
from dagster._core.definitions.partitions.context import partition_loading_context

from stockidence.ingest.endpoints import Cadence, scheduled_endpoints


@pytest.fixture
def defs():
    from stockidence.definitions import defs

    return defs


def test_definitions_expose_jobs_schedules_assets(defs):
    job_names = {j.name for j in defs.resolve_all_job_defs()}
    assert {"monthly_ingest", "weekdays_ingest", "daily_ingest"} <= job_names

    schedule_names = {s.name for s in defs.schedules}
    assert {"monthly_schedule", "weekdays_schedule", "daily_schedule"} <= schedule_names

    assert any("ticker_data" in str(k) for k in defs.resolve_asset_graph().get_all_asset_keys())


def test_ticker_asset_has_dynamic_ticker_partitions(defs):
    asset_def = defs.resolve_assets_def("ticker_data")
    assert asset_def.partitions_def.name == "ticker"  # type: ignore[union-attr]


def test_cadence_jobs_follow_registry():
    def names(job_name):
        cadence = {
            "monthly_ingest": Cadence.MONTHLY,
            "weekdays_ingest": Cadence.WEEKDAYS,
            "daily_ingest": Cadence.DAILY,
        }[job_name]
        return {spec.name for spec in scheduled_endpoints() if spec.cadence == cadence}

    assert "commodities.gold" in names("monthly_ingest")
    assert "macro.cpi" in names("monthly_ingest")
    assert "top_gainers_losers" in names("weekdays_ingest")
    assert "ipo_calendar" in names("weekdays_ingest")
    assert "market_news" in names("daily_ingest")
    assert "quote" not in names("daily_ingest")


def test_ticker_data_asset_runs_with_fake_engine(tmp_path):
    from stockidence.definitions import ticker_data
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()

    class FakeEngine:
        warehouse = wh

        def __init__(self):
            self.seen: list[tuple[str, str]] = []

        def ingest_on_demand(self, endpoint, dimension, now=None):
            self.seen.append((endpoint, dimension))
            return FakeResult()

    class FakeResult:
        reason = "fake fetch"
        rows_written = 0

    engine = FakeEngine()
    instance = DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("ticker", ["AAPL"])
    with partition_loading_context(dynamic_partitions_store=instance):
        result = materialize(
            [ticker_data],
            resources={"engine": engine},
            partition_key="AAPL",
            raise_on_error=True,
            instance=instance,
        )
    assert result.success
    # transcript skipped (no earnings calendar row) but every other
    # on-demand endpoint was offered to the engine at ticker dimension
    assert ("quote", "AAPL") in engine.seen
    assert ("prices.daily", "AAPL") in engine.seen
    assert not any(endpoint == "earnings_call_transcript" for endpoint, _ in engine.seen)