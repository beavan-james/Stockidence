"""Dagster definitions: registry-driven scheduled jobs + model refresh.

The registry (endpoints.py) is the single source of truth: cadence groups
become jobs and schedules bind them. Transform logic lives in plain
functions (ingest/staging/mart); Dagster objects are thin wrappers.

    dagster dev -f src/stockidence/definitions.py

Triggering model (push, no sensors): the frontend calls
POST /api/pipeline/refresh, which launches ``refresh_tickers`` directly
via GraphQL. Nothing polls.

Exposes:
  - monthly_ingest / weekdays_ingest / daily_ingest jobs (schedule-bound)
  - quarterly_model_refresh job (schedule-bound): universe refresh ->
    quarterly dataset rebuild -> notebook retrain + ranking export
  - refresh_tickers job (frontend-triggered): on-demand per-ticker
    ingest + derived rebuilds + scoring
  - ticker_data asset with a dynamic ticker partition per lookup
    (manual materialization path)
"""

from datetime import datetime, timezone
from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetSelection,
    Config,
    DefaultScheduleStatus,
    Definitions,
    DynamicPartitionsDefinition,
    OpExecutionContext,
    in_process_executor,
    job,
    op,
    resource,
    schedule,
    asset,
)

from .ingest.endpoints import Cadence, on_demand_endpoints, scheduled_endpoints
from .ingest.engine import IngestEngine
from .ingest.refresh import refresh_tickers
from .mart.mart import (
    rebuild_advanced_analytics,
    rebuild_fred_market as rebuild_fred_mart,
    rebuild_prices_monthly,
    rebuild_prices_weekly,
    rebuild_technical_indicators,
)
from .mart.scoring import score_ticker
from .staging.staging import rebuild_fred_market as rebuild_fred_staging
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


def _make_cadence_job(cadence: Cadence, post_derived: tuple[tuple[str, Any], ...] = ()):
    """Build a scheduled ingestion job for one cadence group.

    `post_derived` is a sequence of (label, rebuild_fn) market-wide derivations
    that run AFTER the raw lands — used by the daily job to rebuild FRED
    staging + mart from the freshly fetched index series. Unlike the per-ticker
    derived assets, these have no API calls and no ticker partition.
    """
    names = [spec.name for spec in scheduled_endpoints()
             if spec.cadence == cadence]
    if not names:
        return None

    @op(name=f"ingest_{cadence.value}_op", required_resource_keys={"engine"})
    def ingest_cadence(context) -> None:
        engine = context.resources.engine
        for name in names:
            result = engine.ingest_scheduled(name, now=_now())
            context.log.info(
                f"[scheduled:{name}] {result.reason} ({result.rows_written} rows)")

    derived_ops: list[Any] = []
    for i, (label, rebuild) in enumerate(post_derived):
        @op(name=f"{cadence.value}_{label}_op", required_resource_keys={"engine"})
        def derive_cadence(context, _rebuild: Any = rebuild, _label: str = label) -> None:
            rows = _rebuild(context.resources.engine.warehouse)
            context.log.info(f"[derived:{_label}] rebuilt {rows} rows")
        derived_ops.append(derive_cadence)

    @job(name=f"{cadence.value}_ingest")
    def cadence_job():
        ingest_cadence()
        for op in derived_ops:
            op()

    return cadence_job


monthly_job = _make_cadence_job(Cadence.MONTHLY)
weekdays_job = _make_cadence_job(Cadence.WEEKDAYS)
daily_job = _make_cadence_job(
    Cadence.DAILY,
    post_derived=(("fred_staging", rebuild_fred_staging), ("fred_mart", rebuild_fred_mart)),
)


@schedule(job=monthly_job, cron_schedule="0 2 1 * *",
          default_status=DefaultScheduleStatus.RUNNING)
def monthly_schedule() -> dict:  # noqa: ANN401
    """01:00 UTC on the 1st of each month: commodities, macro, symbols."""
    return {}


@schedule(job=weekdays_job, cron_schedule="30 21 * * 1-5",
          default_status=DefaultScheduleStatus.RUNNING)
def weekdays_schedule() -> dict:  # noqa: ANN401
    """21:30 UTC on trading days: right after the US close (20:00 UTC in
    DST, 21:00 UTC in winter), so gainers/losers and IPO + earnings
    calendars capture that day's session. The previous midnight-UTC cron
    skipped Friday's session entirely and ran Monday against stale data."""
    return {}


@schedule(job=daily_job, cron_schedule="0 1 * * *",
          default_status=DefaultScheduleStatus.RUNNING)
def daily_schedule() -> dict:  # noqa: ANN401
    """Daily market-persistent news sentiment."""
    return {}


@asset(partitions_def=ticker_partitions, required_resource_keys={"engine"})
def ticker_data(context: AssetExecutionContext) -> None:
    """On-demand per-ticker fetch (manual materialization path).

    The staleness gate decides which endpoints need a call; the
    frontend-triggered path runs the same logic through the
    ``refresh_tickers`` job instead.
    """
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
                context.log.info(
                    f"[{ticker}] no earnings period on record; skipping transcript")
                continue
            dimension = f"{ticker}|{latest[1]}|{latest[0]}"
        result = engine.ingest_on_demand(endpoint, dimension, now=_now())
        context.log.info(
            f"[{ticker}:{endpoint}] {result.reason} ({result.rows_written} rows)")


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
        rows = rebuild(context.resources.engine.warehouse,
                       context.partition_key)
        context.log.info(
            f"[derived:{name}:{context.partition_key}] rebuilt {rows} rows")

    return _asset


stg_prices_daily = _derived_asset(
    "stg_prices_daily", rebuild_prices_daily, deps=[ticker_data])
m_prices_weekly = _derived_asset(
    "m_prices_weekly", rebuild_prices_weekly, deps=[stg_prices_daily])
m_prices_monthly = _derived_asset(
    "m_prices_monthly", rebuild_prices_monthly, deps=[stg_prices_daily])
m_advanced_analytics = _derived_asset(
    "m_advanced_analytics", rebuild_advanced_analytics, deps=[stg_prices_daily])
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


class RefreshTickersConfig(Config):
    """Tickers to refresh, e.g. {"tickers": ["AAPL", "MSFT"]}."""

    tickers: list[str]


@op(required_resource_keys={"engine"})
def refresh_tickers_op(context: OpExecutionContext, config: RefreshTickersConfig) -> dict:
    """Frontend-triggered per-ticker refresh: ingest + derived + score.

    Incremental — with no watermark on record the staleness gate pulls full
    history automatically, so new tickers need no special-casing.
    """
    engine = context.resources.engine
    tickers = [t.strip().upper() for t in config.tickers if t.strip()]
    return refresh_tickers(engine, tickers, score=True, log=context.log.info)


@job(name="refresh_tickers")
def refresh_tickers_job() -> None:
    """On-demand job launched by the frontend via POST /api/pipeline/refresh."""
    refresh_tickers_op()


@op(required_resource_keys={"engine"})
def quarterly_refresh_op(context: OpExecutionContext) -> dict:
    """Incremental refresh of the whole universe (recent quarter only).

    Watermarks stay intact, so each endpoint fetches only what went stale —
    prices continue from the high watermark, fundamentals re-pull per TTL.
    Failed fetches retry 3x each, then are recorded and skipped.
    """
    from .quarterly import quarterly_universe

    engine = context.resources.engine
    universe = quarterly_universe()
    context.log.info(f"quarterly refresh: {len(universe)} tickers")
    return refresh_tickers(engine, universe, log=context.log.info)


@op
def rebuild_dataset_op(context: OpExecutionContext, prev: dict) -> dict:
    """Rebuild train_dataset_quarterly.parquet from the refreshed mart."""
    from .quarterly import rebuild_quarterly_dataset

    info = rebuild_quarterly_dataset()
    context.log.info(
        f"[dataset] {info['rows']} rows, {info['tickers']} tickers "
        f"({info['date_min']} -> {info['date_max']})"
    )
    return {**prev, "dataset": info}


@op
def retrain_model_op(context: OpExecutionContext, prev: dict) -> dict:
    """Re-execute the ranking notebook: retrains and exports the snapshot
    to mart.model_rankings (the notebook's final cell)."""
    from .quarterly import retrain_ranking_model

    info = retrain_ranking_model()
    context.log.info(f"[retrain] executed {info['cells_executed']} cells")
    return {**prev, "retrain": info}


@job(name="quarterly_model_refresh")
def quarterly_model_refresh_job() -> None:
    """Quarterly chain: universe refresh -> dataset rebuild -> retrain."""
    retrain_model_op(rebuild_dataset_op(quarterly_refresh_op()))


@schedule(
    job=quarterly_model_refresh_job,
    cron_schedule="0 3 1 1,4,7,10 *",
    default_status=DefaultScheduleStatus.RUNNING,
)
def quarterly_schedule() -> dict:  # noqa: ANN401
    """03:00 UTC on the first day of each quarter (Jan/Apr/Jul/Oct)."""
    return {}


defs = Definitions(
    resources={"engine": engine_resource},
    assets=[ticker_data, stg_prices_daily, m_prices_weekly, m_prices_monthly,
            m_advanced_analytics, m_technical_indicators, ticker_score],
    jobs=[monthly_job, weekdays_job, daily_job, refresh_tickers_job,
          quarterly_model_refresh_job],
    schedules=[monthly_schedule, weekdays_schedule, daily_schedule,
               quarterly_schedule],
    # DuckDB is a single-writer file: with the default multiprocess executor
    # DuckDB is a single-writer file: with the default multiprocess executor
    # every step runs in its own subprocess and the four mart siblings (all
    # depending only on stg_prices_daily) launch concurrently and fight over
    # the write lock. In-process keeps each run's steps sequential; cross-run
    # overlap is still safe because Warehouse.connect retries on lock.
    executor=in_process_executor,
)
