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
from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetSelection,
    Definitions,
    DynamicPartitionsDefinition,
    RunRequest,
    job,
    op,
    resource,
    schedule,
    sensor,
    asset,
)

from .ingest.endpoints import Cadence, on_demand_endpoints, scheduled_endpoints
from .ingest.engine import IngestEngine
from .mart.mart import (
    rebuild_advanced_analytics,
    rebuild_prices_monthly,
    rebuild_prices_weekly,
    rebuild_technical_indicators,
)
from .mart.scoring import score_ticker
from .staging.staging import rebuild_prices_daily
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
                # free-tier calendar only looks ahead ~2 weeks: fall back to
                # the latest reported quarter from /stock/earnings
                latest = engine.warehouse.connect(read_only=True).execute(
                    """
                    SELECT year, quarter FROM raw.raw_eps_surprises
                    WHERE ticker = ? ORDER BY year DESC, quarter DESC LIMIT 1
                    """,
                    [ticker],
                ).fetchone()
            if latest is None:
                context.log.info(f"[{ticker}] no earnings period on record; skipping transcript")
                continue
            dimension = f"{ticker}|{latest[1]}|{latest[0]}"
        result = engine.ingest_on_demand(endpoint, dimension, now=_now())
        context.log.info(f"[{ticker}:{endpoint}] {result.reason} ({result.rows_written} rows)")


def stage_ticker_runs(warehouse: Warehouse, instance) -> list[str]:
    """Consume the request queue: add a dynamic ticker partition per pending
    request and mark them launched. Returns the staged tickers so the sensor
    can emit one RunRequest each. Requests whose runs fail are picked up again
    on the next frontend re-request."""
    pending = warehouse.pending_ticker_requests()
    for ticker in pending:
        instance.add_dynamic_partitions("ticker", [ticker])
    if pending:
        warehouse.mark_ticker_requests_launched(pending)
    return pending


def _derived_asset(name: str, rebuild: Any, deps: AssetSelection | list | object) -> object:
    """Declare one per-ticker derived asset (staging cleaning or mart aggregate).

    `name` is the asset key AND the table name it rebuilds (stg_*/m_*), so
    the Dagster key stays aligned with the warehouse table.
    """

    @asset(
        name=name,
        partitions_def=ticker_partitions,
        required_resource_keys={"engine"},
        deps=deps,
    )
    def _asset(context: AssetExecutionContext) -> None:
        rows = rebuild(context.resources.engine.warehouse, context.partition_key)
        context.log.info(f"[derived:{name}:{context.partition_key}] rebuilt {rows} rows")

    return _asset


stg_prices_daily = _derived_asset("stg_prices_daily", rebuild_prices_daily, deps=[ticker_data])
m_prices_weekly = _derived_asset("m_prices_weekly", rebuild_prices_weekly, deps=[stg_prices_daily])
m_prices_monthly = _derived_asset("m_prices_monthly", rebuild_prices_monthly, deps=[stg_prices_daily])
m_advanced_analytics = _derived_asset("m_advanced_analytics", rebuild_advanced_analytics, deps=[stg_prices_daily])
m_technical_indicators = _derived_asset(
    "m_technical_indicators", rebuild_technical_indicators, deps=[stg_prices_daily]
)


@asset(
    name="ticker_score",
    partitions_def=ticker_partitions,
    required_resource_keys={"engine"},
    deps=[ticker_data, m_technical_indicators, m_advanced_analytics],
)
def ticker_score(context: AssetExecutionContext) -> None:
    """Deterministic score pipeline for one ticker: reads raw/staging/mart,
    writes the m_confidence_ratings / m_rating_components / m_buy_plans
    snapshot tables (one row per ticker, latest run wins)."""
    ticker = context.partition_key
    result = score_ticker(context.resources.engine.warehouse, ticker)
    context.log.info(
        f"[score:{ticker}] {result.rating} (confidence {result.confidence_score:.1f}, "
        f"val {next(c.score for c in result.categories if c.name == 'valuation'):.1f}, "
        f"vol {result.volatility_score:.1f})"
    )


@sensor(
    target=AssetSelection.keys(
        "ticker_data", "stg_prices_daily", "m_prices_weekly", "m_prices_monthly",
        "m_advanced_analytics", "m_technical_indicators", "ticker_score",
    ),
    minimum_interval_seconds=30,
    required_resource_keys={"engine"},
    description=(
        "Polls control.ticker_requests (written by the frontend), adds a dynamic "
        "ticker partition, and materializes ticker_data so the staleness gate can "
        "decide which endpoints need a fresh call."
    ),
)
def ticker_request_sensor(context) -> None:
    """Event-driven on-demand ingestion: request queue -> partition -> run."""
    warehouse = context.resources.engine.warehouse
    for ticker in stage_ticker_runs(warehouse, context.instance):
        context.log.info(f"[request:{ticker}] launching ticker_data materialization")
        yield RunRequest(run_key=f"ticker_request_{ticker}", partition_key=ticker)


defs = Definitions(
    resources={"engine": engine_resource},
    assets=[ticker_data, stg_prices_daily, m_prices_weekly, m_prices_monthly,
            m_advanced_analytics, m_technical_indicators, ticker_score],
    jobs=[monthly_job, weekdays_job, daily_job],
    schedules=[monthly_schedule, weekdays_schedule, daily_schedule],
    sensors=[ticker_request_sensor],
)