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


def test_sensor_ping_emits_run_request_and_drains_queue(tmp_path):
    """The production loop the frontend depends on: a queued request must
    become exactly one RunRequest on the next sensor ping, flip to launched,
    and register its dynamic partition."""
    from datetime import datetime, timezone

    from dagster import DagsterInstance, build_sensor_context

    from stockidence.definitions import IngestEngine, ticker_request_sensor
    from stockidence.storage import Warehouse

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    now = datetime.now(timezone.utc)
    wh.request_ticker("AAPL", requested_at=now)
    wh.request_ticker("NVDA", requested_at=now)

    instance = DagsterInstance.ephemeral()
    from stockidence.definitions import defs as _defs

    with partition_loading_context(dynamic_partitions_store=instance):
        context = build_sensor_context(
            instance=instance,
            resources={"engine": IngestEngine(wh)},
            repository_def=_defs.get_repository_def(),
        )
        evaluation = ticker_request_sensor.evaluate_tick(context)

    assert sorted(rr.partition_key for rr in evaluation.run_requests) == [
        "AAPL", "NVDA"]
    assert set(instance.get_dynamic_partitions("ticker")) == {"AAPL", "NVDA"}
    assert wh.pending_ticker_requests() == []  # queue drained -> no re-pings

    # a second ping with nothing pending emits no runs (no churn)
    second = ticker_request_sensor.evaluate_tick(
        build_sensor_context(instance=instance,
                             resources={"engine": IngestEngine(wh)}))
    assert second.run_requests == []


def test_full_ticker_run_executes_green_for_partition(tmp_path):
    """Sensor RunRequests launch the full per-ticker asset graph. Materialize
    it end-to-end against a seeded warehouse (fake engine = no network) and
    require success plus a persisted confidence rating."""
    from dagster import ResourceDefinition, materialize

    from stockidence.ingest.engine import IngestEngine
    from stockidence.definitions import (
        m_advanced_analytics,
        m_prices_monthly,
        m_prices_weekly,
        m_technical_indicators,
        stg_prices_daily,
        ticker_data,
        ticker_score,
    )
    from stockidence.storage import Warehouse
    from test_scoring import _seed_bars, _seed_fundamentals, _seed_profile, _seed_quotes, _seed_sentiment

    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    for seed in (_seed_bars, _seed_fundamentals, _seed_profile,
                 _seed_sentiment):
        seed(wh, "UND1")
    _seed_quotes(wh, "UND1", price=319.5)  # last bar close of the ramp

    class FakeResult:
        reason = "fake fetch"
        rows_written = 0

    class FakeEngine:
        warehouse = wh

        def ingest_on_demand(self, endpoint, dimension, now=None):
            return FakeResult()

    instance = DagsterInstance.ephemeral()
    instance.add_dynamic_partitions("ticker", ["UND1"])
    with partition_loading_context(dynamic_partitions_store=instance):
        result = materialize(
            [ticker_data, stg_prices_daily, m_prices_weekly, m_prices_monthly,
             m_advanced_analytics, m_technical_indicators, ticker_score],
            resources={"engine": FakeEngine()},
            partition_key="UND1",
            instance=instance,
            raise_on_error=True,
        )
    assert result.success

    row = wh.connect(read_only=True).execute(
        "SELECT rating, confidence_score FROM mart.m_confidence_ratings "
        "WHERE ticker = 'UND1'"
    ).fetchone()
    assert row is not None
    assert row[0] in ("Buy", "Strong Buy")
    assert 55.0 <= row[1] <= 85.0