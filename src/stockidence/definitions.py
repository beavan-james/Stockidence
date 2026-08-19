"""Dagster definitions: registry-driven scheduled jobs + on-demand ticker asset.

The registry (endpoints.py) is the single source of truth: cadence groups
become jobs, schedules bind them, and the on-demand ticker asset fans a
partitioned request out through the ingestion engine's staleness gate.

    dagster dev -f src/stockidence/definitions.py

Exposes:
  - monthly_ingest / weekdays_ingest / daily_ingest jobs (schedule-bound)
  - ticker_data asset with a dynamic ticker partition per lookup
"""

from datetime import datetime, timezone

from dagster import (
    AssetExecutionContext,
    Definitions,
    DynamicPartitionsDefinition,
    job,
    op,
    resource,
    schedule,
    asset,
)

from .endpoints import Cadence, Trigger, on_demand_endpoints, scheduled_endpoints
from .ingest import IngestEngine
from .storage import Warehouse

ticker_partitions = DynamicPartitionsDefinition(name="ticker")

_ON_DEMAND_ENDPOINTS = tuple(spec.name for spec in on_demand_endpoints())


def _now() -> datetime:
    return datetime.now(timezone.utc)


@resource
def engine_resource() -> IngestEngine:
    warehouse = Warehouse()
    warehouse.init_schema()
    return IngestEngine(warehouse)


def _make_cadence_job(cadence: Cadence):
    names = [spec.name for spec in scheduled_endpoints() if spec.cadence == cadence]
    if not names:
        return None

    @op(name=f"ingest_{cadence.value}_op", required_resource_keys={"engine"})
    def ingest_cadence(ctx) -> None:
        engine = ctx.resources.engine
        for name in names:
            result = engine.ingest_scheduled(name, now=_now())
            ctx.log.info(f"[scheduled:{name}] {result.reason} ({result.rows_written} rows)")

    @job(name=f"{cadence.value}_ingest")
    def cadence_job():
        ingest_cadence()

    return cadence_job


monthly_job = _make_cadence_job(Cadence.MONTHLY)
weekdays_job = _make_cadence_job(Cadence.WEEKDAYS)
daily_job = _make_cadence_job(Cadence.DAILY)


@schedule(job=monthly_job, cron_schedule="0 2 1 * *")
def monthly_schedule() -> dict:  # noqa: ANN401
    """01:00 UTC on the 1st of each month: commodities, macro, symbols."""
    return {}


@schedule(job=weekdays_job, cron_schedule="0 0 * * 1-5")
def weekdays_schedule() -> dict:  # noqa: ANN401
    """After market close: gainers/losers, IPO + earnings calendars."""
    return {}


@schedule(job=daily_job, cron_schedule="0 1 * * *")
def daily_schedule() -> dict:  # noqa: ANN401
    """Daily market-persistent news sentiment."""
    return {}


@asset(partitions_def=ticker_partitions, required_resource_keys={"engine"})
def ticker_data(context: AssetExecutionContext) -> None:
    """On-demand per-ticker fetch: the frontend adds a ticker partition,
    then the engine's staleness gate decides which endpoints need a call."""
    ticker = context.partition_key
    engine = context.resources.engine
    for endpoint in _ON_DEMAND_ENDPOINTS:
        dimension = ticker
        if endpoint == "earnings_call_transcript":
            latest = engine.warehouse.connect(read_only=True).execute(
                """
                SELECT year, quarter FROM raw.raw_earnings_calendar
                WHERE symbol = ?
                  AND CAST(json_extract_string(payload, '$.date') AS DATE) <= current_date
                ORDER BY year DESC, quarter DESC LIMIT 1
                """,
                [ticker],
            ).fetchone()
            if latest is None:
                context.log.info(f"[{ticker}] no earnings calendar entry; skipping transcript")
                continue
            dimension = f"{ticker}|{latest[1]}|{latest[0]}"
        result = engine.ingest_on_demand(endpoint, dimension, now=_now())
        context.log.info(f"[{ticker}:{endpoint}] {result.reason} ({result.rows_written} rows)")


defs = Definitions(
    resources={"engine": engine_resource},
    assets=[ticker_data],
    jobs=[monthly_job, weekdays_job, daily_job],
    schedules=[monthly_schedule, weekdays_schedule, daily_schedule],
)