"""Dagster definitions: registry-driven scheduled jobs + model refresh.

The registry (endpoints.py) is the single source of truth: cadence groups
become jobs and schedules bind them. Transform logic lives in plain
functions (ingest/staging/mart); Dagster objects are thin wrappers.

    dagster dev -f src/stockidence/definitions.py

Triggering model (push, no sensors): the frontend calls
POST /api/pipeline/refresh, which launches ``refresh_tickers`` directly
via GraphQL. Nothing polls.

Exposes:
  - monthly_ingest / weekdays_ingest / overnight_ingest / daily_ingest jobs
    (schedule-bound)
  - quarterly_model_refresh job (schedule-bound): universe refresh ->
    quarterly dataset rebuild -> notebook retrain + ranking export
  - weekly_model_refresh job (schedule-bound, Fridays after the close):
    universe refresh -> weekly dataset rebuild -> refit + Stocks of the
    Week export; weekly_rank re-runs the last two steps alone
  - refresh_tickers job (frontend-triggered): on-demand per-ticker
    ingest + derived rebuilds + scoring
  - refresh_quotes job (frontend-triggered): quote-only pull for explicit
    user refresh (portfolio button) — no rebuilds, no scoring
  - daily_digest job (schedule-bound, weekdays 07:30 New York): news pull
    -> news staging -> the day's news digest -> the picked stories' article
    pages -> their text -> story cards -> the daily paragraph (local model)
  - weekly_digest job (schedule-bound, Saturdays 07:30 New York): the same
    chain into the week's digest and the weekly article
  - ticker_data asset with a dynamic ticker partition per lookup
    (manual materialization path)

Every op in a scheduled job claims a slot in the "warehouse" concurrency
pool (limit 1, dagster.yaml), so two scheduled jobs never write DuckDB at
once: one waits at an op boundary instead of failing on the lock. The two
model ops of the digest jobs are the exception: they never open the
warehouse, so they don't hold the slot while the model writes.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from dagster import (
    AssetExecutionContext,
    AssetSelection,
    Config,
    DefaultScheduleStatus,
    Definitions,
    DynamicPartitionsDefinition,
    Failure,
    OpExecutionContext,
    asset,
    in_process_executor,
    job,
    op,
    resource,
    schedule,
)

from .ingest.agency_feeds import pull_agency_releases
from .ingest.articles import MAX_REQUESTS, digests_to_read, fetch_digest_articles
from .ingest.endpoints import Cadence, on_demand_endpoints, scheduled_endpoints
from .ingest.engine import IngestEngine
from .ingest.refresh import refresh_tickers
from .ingest.sec_filings import new_client as new_sec_client
from .ingest.sec_filings import pull_8k_releases
from .mart.mart import (
    rebuild_advanced_analytics,
    rebuild_prices_monthly,
    rebuild_prices_weekly,
    rebuild_technical_indicators,
)
from .mart.mart import (
    rebuild_fred_market as rebuild_fred_mart,
)
from .mart.news_digest import (
    build_daily_digests,
    build_weekly_digests,
    latest_digest_date,
    latest_weekly_date,
)
from .mart.scoring import score_ticker
from .staging.article_text import rebuild_article_text
from .staging.staging import (
    balance_sheet_sources,
    rebuild_financials_reported,
    rebuild_news_articles,
    rebuild_prices_daily,
)
from .staging.staging import rebuild_fred_market as rebuild_fred_staging
from .storage import Warehouse
from .summaries.cards import Card
from .summaries.model import Ollama
from .summaries.run import CardRun, SummaryRun, make_cards, write_summaries
from .summaries.store import read_inputs, save_cards, save_summaries

ticker_partitions = DynamicPartitionsDefinition(name="ticker")

_ON_DEMAND_ENDPOINTS = tuple(spec.name for spec in on_demand_endpoints())

# DuckDB takes one writer at a time, and the retrains keep it busy for
# hours. Every op of a scheduled or retrain job claims this pool (limit 1
# in dagster.yaml), so a job that lands on top of another waits for the
# slot instead of failing after Warehouse.connect's ~3 minutes of retries.
# The site-triggered jobs (refresh_tickers, refresh_quotes) stay out: a
# visitor never waits behind a retrain, and the retries cover them.
WAREHOUSE_POOL = "warehouse"


def _now() -> datetime:
    return datetime.now(UTC)


@resource
def engine_resource() -> IngestEngine:
    """Dagster starts resources before an op claims its pool slot, so this
    must not open the warehouse: the first op to connect creates the schema."""
    return IngestEngine(Warehouse(create_schema=True))


@resource
def llm_resource() -> Ollama:
    """The local model at OLLAMA_URL. Nothing connects until the first call."""
    return Ollama.from_env()


def _make_cadence_job(cadence: Cadence, post_derived: tuple[tuple[str, Any], ...] = ()):
    """Build a scheduled ingestion job for one cadence group.

    `post_derived` is a sequence of (label, rebuild_fn) market-wide derivations
    that run AFTER the raw lands — used by the daily job to rebuild FRED
    staging + mart from the freshly fetched index series. Unlike the per-ticker
    derived assets, these have no API calls and no ticker partition.
    """
    names = [spec.name for spec in scheduled_endpoints() if spec.cadence == cadence]
    if not names:
        return None

    @op(name=f"ingest_{cadence.value}_op", required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
    def ingest_cadence(context) -> None:
        engine = context.resources.engine
        for name in names:
            result = engine.ingest_scheduled(name, now=_now())
            context.log.info(f"[scheduled:{name}] {result.reason} ({result.rows_written} rows)")

    derived_ops: list[Any] = []
    for i, (label, rebuild) in enumerate(post_derived):

        @op(
            name=f"{cadence.value}_{label}_op",
            required_resource_keys={"engine"},
            pool=WAREHOUSE_POOL,
        )
        def derive_cadence(context, _rebuild: Any = rebuild, _label: str = label) -> None:
            rows = _rebuild(context.resources.engine.warehouse)
            context.log.info(f"[derived:{_label}] rebuilt {rows} rows")

        derived_ops.append(derive_cadence)

    @job(name=f"{cadence.value}_ingest")
    def cadence_job():
        ingest_cadence()
        for derived_op in derived_ops:
            derived_op()

    return cadence_job


monthly_job = _make_cadence_job(Cadence.MONTHLY)
weekdays_job = _make_cadence_job(Cadence.WEEKDAYS)
overnight_job = _make_cadence_job(Cadence.OVERNIGHT)
daily_job = _make_cadence_job(
    Cadence.DAILY,
    post_derived=(("fred_staging", rebuild_fred_staging), ("fred_mart", rebuild_fred_mart)),
)


@schedule(job=monthly_job, cron_schedule="0 2 1 * *", default_status=DefaultScheduleStatus.RUNNING)
def monthly_schedule() -> dict:
    """01:00 UTC on the 1st of each month: commodities, macro, symbols."""
    return {}


@schedule(
    job=weekdays_job, cron_schedule="30 21 * * 1-5", default_status=DefaultScheduleStatus.RUNNING
)
def weekdays_schedule() -> dict:
    """21:30 UTC on weekdays, after the US close (20:00 UTC in DST, 21:00 UTC
    in winter): the IPO and earnings calendars."""
    return {}


@schedule(
    job=overnight_job,
    cron_schedule="30 0 * * 2-6",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)
def overnight_schedule() -> dict:
    """00:30 New York time, Tuesday to Saturday: the movers of the session
    that closed the afternoon before. Alpha Vantage's free tier publishes a
    session's list late in the evening; at 17:30 it still served the session
    before. Clear of every other job unless a retrain is still running, and
    then it waits for the pool."""
    return {}


@schedule(job=daily_job, cron_schedule="0 1 * * *", default_status=DefaultScheduleStatus.RUNNING)
def daily_schedule() -> dict:
    """Daily market news (Finnhub) plus the FRED market indexes."""
    return {}


@op(name="ingest_news_op", required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def ingest_news_op(context) -> dict:
    engine = context.resources.engine
    result = engine.ingest_scheduled("market_news", now=_now())
    context.log.info(f"[scheduled:market_news] {result.reason} ({result.rows_written} rows)")
    return {"news_rows": result.rows_written}


@job(name="news_ingest")
def news_job():
    """News-only pull (Finnhub general news, latest ~100 articles, upsert
    on article_id so repeats are idempotent). The 01:00 daily job also pulls
    news; these two add the morning/evening refreshes."""
    ingest_news_op()


@schedule(job=news_job, cron_schedule="0 11 * * *", default_status=DefaultScheduleStatus.RUNNING)
def news_morning_schedule() -> dict:
    """11:00 UTC (~7am ET): morning news pull."""
    return {}


@schedule(job=news_job, cron_schedule="0 23 * * *", default_status=DefaultScheduleStatus.RUNNING)
def news_evening_schedule() -> dict:
    """23:00 UTC (~7pm ET): evening news pull."""
    return {}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def ingest_primary_news_op(context: OpExecutionContext, prev: dict) -> dict:
    """Pull the primary sources the digests' stories come from: SEC's
    ticker list (when older than its 7-day TTL), the tracked companies' new
    8-Ks and the agencies' new releases (endpoints sec_company_tickers,
    sec_8k_releases, agency_releases).

    Each source fails on its own, with a warning: the digest is built from
    whatever landed. The warehouse is open only to plan and to land, not
    during requests; the op keeps its pool slot for the minute or two it
    runs.
    """
    engine = context.resources.engine
    now = _now()
    out: dict[str, Any] = {}
    try:
        r = engine.ingest_on_demand("sec_company_tickers", "sec_company_tickers", now=now)
        context.log.info(f"[sec_company_tickers] {r.reason} ({r.rows_written} rows)")
        out["sec_company_tickers"] = r.rows_written
    except Exception as exc:  # noqa: BLE001 -- the 8-K pull uses the list already landed
        context.log.warning(f"[sec_company_tickers] failed: {exc}")
    try:
        info = pull_8k_releases(engine.warehouse, new_sec_client(), now=now)
        context.log.info(f"[sec_8k_releases] {info}")
        if info.get("failed") or info.get("rate_limited") or info.get("capped"):
            context.log.warning(
                f"[sec_8k_releases] {len(info.get('failed', []))} filings failed, rate limited: "
                f"{info.get('rate_limited')}, capped: {info.get('capped')}; the cursor waits for them")
        out["sec_8k_releases"] = info.get("landed", 0)
    except Exception as exc:  # noqa: BLE001 -- the cursor is unchanged, the next run retries
        context.log.warning(f"[sec_8k_releases] failed: {exc}")
    try:
        info = pull_agency_releases(engine.warehouse, now=now)
        context.log.info(f"[agency_releases] {info}")
        out["agency_releases"] = info["landed"]
    except Exception as exc:  # noqa: BLE001 -- releases not landed are read again next run
        context.log.warning(f"[agency_releases] failed: {exc}")
    return {**prev, "primary": out}


# A session with no article for this long means the general feed (latest
# ~100 articles per pull) likely missed news between pulls. Only digests
# built from the news feed have a gap.
_DIGEST_GAP_WARN_MINUTES = 120


class DailyDigestConfig(Config):
    """Which digests to build: the one dated `digest_date` (YYYY-MM-DD; empty
    means the newest whose window has closed) and the `days - 1` weekdays
    before it. days > 1 backfills the archive from news already landed."""

    digest_date: str = ""
    days: int = 1


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def stage_news_op(context: OpExecutionContext, prev: dict) -> dict:
    """Restage the articles landed since the last run into stg_news_articles."""
    rows = rebuild_news_articles(context.resources.engine.warehouse)
    context.log.info(f"[derived:stg_news_articles] restaged {rows} articles")
    return {**prev, "staged": rows}


class WeeklyDigestConfig(Config):
    """Which weekly digests to build: the one dated Friday `digest_date`
    (YYYY-MM-DD; empty means the newest whose window has closed) and the
    `weeks - 1` before it."""

    digest_date: str = ""
    weeks: int = 1


def _log_digests(context: OpExecutionContext, built: list[dict]) -> None:
    for d in built:
        tag = f"[digest:{d['period']}:{d['digest_date']}]"
        context.log.info(
            f"{tag} {d['picked']} of {d['stories']} stories from "
            f"{d['articles']} articles ({d['routine_dropped']} routine, "
            f"{d['commentary_dropped']} commentary dropped), {d['outlets']} outlets"
        )
        if d["session_gap_minutes"] >= _DIGEST_GAP_WARN_MINUTES:
            context.log.warning(
                f"{tag} no article for {d['session_gap_minutes']} minutes of a session: "
                "the news feed likely missed stories between pulls"
            )


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def build_digest_op(context: OpExecutionContext, config: DailyDigestConfig, prev: dict) -> dict:
    """Pick the day's top stories into mart.news_digest_* (one digest per date)."""
    last = (
        date.fromisoformat(config.digest_date) if config.digest_date else latest_digest_date(_now())
    )
    built = build_daily_digests(context.resources.engine.warehouse, last, max(config.days, 1))
    _log_digests(context, built)
    return {**prev, "digests": built}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def build_weekly_digest_op(
    context: OpExecutionContext, config: WeeklyDigestConfig, prev: dict
) -> dict:
    """Pick the week's top stories into mart.news_digest_* (period 'weekly')."""
    last = (
        date.fromisoformat(config.digest_date) if config.digest_date else latest_weekly_date(_now())
    )
    built = build_weekly_digests(context.resources.engine.warehouse, last, max(config.weeks, 1))
    _log_digests(context, built)
    return {**prev, "digests": built}


class FetchArticlesConfig(Config):
    """Page requests allowed in one run; raise it for a backfill."""

    max_requests: int = MAX_REQUESTS


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def fetch_articles_op(context: OpExecutionContext, config: FetchArticlesConfig, prev: dict) -> dict:
    """Fetch the article pages behind the stories the digests just picked
    into raw.news_article_pages (NEWS_SUMMARIES.md has the rules).

    The warehouse is open only to plan and to land, not while pages are
    fetched; the op keeps its pool slot for the few minutes it runs.
    """
    digests = digests_to_read(prev.get("digests", []))
    info = fetch_digest_articles(
        context.resources.engine.warehouse, digests, now=_now(), max_requests=config.max_requests
    )
    context.log.info(
        f"[articles] read {info['stories_read']} of {info['stories']} stories still unread "
        f"with {info['page_requests']} page requests: {info['outcomes']}"
    )
    if info["skipped_domains"]:
        context.log.info(
            f"[articles] skipped by robots.txt or unreachable: {info['skipped_domains']}"
        )
    if info["capped"]:
        context.log.warning(
            f"[articles] stopped at {config.max_requests} page requests; the rest wait for the next run"
        )
    return {**prev, "articles": info}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def stage_article_text_op(context: OpExecutionContext, prev: dict) -> dict:
    """Extract each new page's main text into staging.stg_news_article_text."""
    rows = rebuild_article_text(context.resources.engine.warehouse, now=_now())
    context.log.info(f"[derived:stg_news_article_text] extracted {rows} pages")
    return {**prev, "article_text": rows}


# --- News summaries (NEWS_SUMMARIES.md) ---------------------------------------
# Read, model, save, model, save. The two model ops stay out of the
# warehouse pool and never open the warehouse, so 30-55 minutes of model
# work never blocks another job; the read and save ops take the slot for
# seconds.


class RedoConfig(Config):
    """redo: make these digests' cards (or summaries) again even where they
    exist, after a prompt change, say."""

    redo: bool = False


def _built(prev: dict) -> list[tuple[str, date]]:
    return [
        (d["period"], date.fromisoformat(str(d["digest_date"]))) for d in prev.get("digests", [])
    ]


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def read_summary_inputs_op(context: OpExecutionContext, prev: dict) -> dict:
    """Read the stories, their article text and existing cards and summaries."""
    inputs = read_inputs(
        context.resources.engine.warehouse, digests_to_read(prev.get("digests", [])), _built(prev)
    )
    readable = sum(1 for s in inputs.stories if s.texts)
    context.log.info(
        f"[summaries] {len(inputs.stories)} stories ({readable} with article text), "
        f"{len(inputs.cards)} cards already made; writing {inputs.write or 'nothing'}"
    )
    return {**prev, "summary_inputs": inputs}


@op(required_resource_keys={"llm"})
def write_story_cards_op(context: OpExecutionContext, config: RedoConfig, prev: dict) -> dict:
    """One fact card per story that has none (model; no warehouse)."""

    def logged(card: Card) -> None:
        note = f": {'; '.join(card.problems)}" if card.problems else ""
        context.log.info(
            f"[card] {card.story_key} {card.status} in {card.seconds:.0f}s "
            f"({card.input_tokens} tokens in, {card.output_tokens} out){note}"
        )

    run = make_cards(
        context.resources.llm, prev["summary_inputs"], _now, redo=config.redo, on_card=logged
    )
    return {**prev, "card_run": run}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def save_story_cards_op(context: OpExecutionContext, prev: dict) -> dict:
    """Store the new cards in mart.news_story_cards; fail the run after
    saving them if the model server went away."""
    run: CardRun = prev["card_run"]
    saved = save_cards(context.resources.engine.warehouse, list(run.made))
    fallbacks = sum(c.status == "fallback" for c in run.made)
    context.log.info(f"[cards] saved {saved} ({fallbacks} from the feed summary)")
    if run.error:
        raise Failure(f"model server unavailable after {saved} cards: {run.error}")
    return prev


@op(required_resource_keys={"llm"})
def write_summaries_op(context: OpExecutionContext, config: RedoConfig, prev: dict) -> dict:
    """The daily paragraph or the weekly article (model; no warehouse)."""
    inputs = prev["summary_inputs"]
    cards = {**inputs.cards, **{c.story_key: c for c in prev["card_run"].made}}
    run = write_summaries(context.resources.llm, inputs, cards, _now, redo=config.redo)
    for s in run.written:
        tag = f"[summary:{s.period}:{s.digest_date}:{s.part}]"
        note = f": {'; '.join(s.problems)}" if s.problems else ""
        words = len(s.body.split()) if s.body else 0
        context.log.info(f"{tag} {s.status}, {words} words{note}")
    if run.skipped:
        context.log.info(f"[summaries] already written from the same stories: {list(run.skipped)}")
    if run.empty:
        context.log.warning(f"[summaries] no stories to write about: {list(run.empty)}")
    return {**prev, "summary_run": run}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def save_summaries_op(context: OpExecutionContext, prev: dict) -> dict:
    """Store the summaries in mart.news_summaries; fail the run after saving
    them if the model server went away."""
    run: SummaryRun = prev["summary_run"]
    saved = save_summaries(context.resources.engine.warehouse, list(run.written))
    context.log.info(f"[summaries] saved {saved} parts")
    if run.error:
        raise Failure(f"model server unavailable after {saved} summary parts: {run.error}")
    rest = {k: v for k, v in prev.items() if k not in ("summary_inputs", "card_run", "summary_run")}
    return {**rest, "cards": len(prev["card_run"].made), "summary_parts": saved}


def _summarize(prev: Any) -> Any:
    """The five summary ops, after a digest job's article text."""
    inputs = read_summary_inputs_op(prev)
    return save_summaries_op(write_summaries_op(save_story_cards_op(write_story_cards_op(inputs))))


@job(name="daily_digest")
def daily_digest_job() -> None:
    """Weekday morning chain: news pull -> 8-Ks and agency releases -> news
    staging -> digest -> the picked stories' pages -> their text -> cards ->
    the paragraph."""
    text = stage_article_text_op(fetch_articles_op(build_digest_op(stage_news_op(
        ingest_primary_news_op(ingest_news_op())))))
    _summarize(text)


@schedule(
    job=daily_digest_job,
    cron_schedule="30 7 * * 1-5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)
def daily_digest_schedule() -> dict:
    """07:30 New York time on weekdays, before the open: the digest covers
    the 24 hours to 07:00 (the weekend too, on Mondays). New York time, so
    DST never shifts it."""
    return {}


@job(name="weekly_digest")
def weekly_digest_job() -> None:
    """Saturday morning chain: news pull -> news staging -> the week's digest
    -> article pages for its stories and the week's daily stories -> text
    -> cards for stories still without one -> the weekly article."""
    text = stage_article_text_op(
        fetch_articles_op(build_weekly_digest_op(stage_news_op(ingest_news_op())))
    )
    _summarize(text)


@schedule(
    job=weekly_digest_job,
    cron_schedule="30 7 * * 6",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)
def weekly_digest_schedule() -> dict:
    """07:30 New York time on Saturdays: the week's digest covers the seven
    days to 07:00, so Friday's session, its evening and the earnings
    released after the close are in."""
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
            latest = (
                engine.warehouse.connect(read_only=True)
                .execute(
                    """
                SELECT year, quarter FROM raw.raw_earnings_calendar
                WHERE symbol = ?
                  AND CAST(json_extract_string(payload, '$.date') AS DATE) <= current_date
                ORDER BY year DESC, quarter DESC LIMIT 1
                """,
                    [ticker],
                )
                .fetchone()
            )
            if latest is None:
                # free-tier calendar only looks ahead ~2 weeks: fall back to
                # the latest reported quarter from /stock/earnings
                latest = (
                    engine.warehouse.connect(read_only=True)
                    .execute(
                        """
                    SELECT year, quarter FROM raw.raw_eps_surprises
                    WHERE ticker = ? ORDER BY year DESC, quarter DESC LIMIT 1
                    """,
                        [ticker],
                    )
                    .fetchone()
                )
            if latest is None:
                context.log.info(f"[{ticker}] no earnings period on record; skipping transcript")
                continue
            dimension = f"{ticker}|{latest[1]}|{latest[0]}"
        result = engine.ingest_on_demand(endpoint, dimension, now=_now())
        context.log.info(f"[{ticker}:{endpoint}] {result.reason} ({result.rows_written} rows)")


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
m_prices_monthly = _derived_asset(
    "m_prices_monthly", rebuild_prices_monthly, deps=[stg_prices_daily]
)
m_advanced_analytics = _derived_asset(
    "m_advanced_analytics", rebuild_advanced_analytics, deps=[stg_prices_daily]
)
m_technical_indicators = _derived_asset(
    "m_technical_indicators", rebuild_technical_indicators, deps=[stg_prices_daily]
)
stg_financials_reported = _derived_asset(
    "stg_financials_reported", rebuild_financials_reported, deps=[ticker_data]
)


@asset(
    name="ticker_score",
    partitions_def=ticker_partitions,
    required_resource_keys={"engine"},
    deps=[ticker_data, stg_financials_reported, m_technical_indicators, m_advanced_analytics],
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


class RefreshQuotesConfig(Config):
    """Tickers whose cached quotes should be refreshed, e.g. {"tickers": ["AAPL", "MSFT"]}."""

    tickers: list[str]


@op(required_resource_keys={"engine"})
def refresh_quotes_op(context: OpExecutionContext, config: RefreshQuotesConfig) -> dict:
    """Quote-only refresh for explicit user action (portfolio Refresh button).

    One staleness-gated Finnhub call per ticker (1-minute TTL) — no derived
    rebuilds, no scoring, so it stays cheap enough to run on demand for a
    whole portfolio.
    """
    engine = context.resources.engine
    tickers = [t.strip().upper() for t in config.tickers if t.strip()][:25]
    now = _now()
    status = {}
    for t in tickers:
        result = engine.ingest_on_demand("quote", t, now=now)
        status[t] = {"fetched": result.fetched, "reason": result.reason}
        context.log.info(f"[quote:{t}] {result.reason} ({result.rows_written} rows)")
    return {"tickers": tickers, "status": status}


@job(name="refresh_quotes")
def refresh_quotes_job() -> None:
    """Quote-only pull launched by the frontend via POST /api/quotes/refresh."""
    refresh_quotes_op()


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def quarterly_refresh_op(context: OpExecutionContext) -> dict:
    """Incremental refresh of every ticker in the warehouse (recent quarter only).

    Watermarks stay intact, so each endpoint fetches only what went stale —
    prices continue from the high watermark, fundamentals re-pull per TTL.
    Failed fetches retry 3x each, then are recorded and skipped.
    """
    from .quarterly import quarterly_universe

    engine = context.resources.engine
    universe = quarterly_universe(engine.warehouse)
    context.log.info(f"quarterly refresh: {len(universe)} tickers")
    summary = refresh_tickers(engine, universe, log=context.log.info)
    if summary["errors"]:
        by_endpoint: dict[str, int] = {}
        for err in summary["errors"]:
            by_endpoint[err["endpoint"]] = by_endpoint.get(err["endpoint"], 0) + 1
        context.log.warning(
            f"quarterly refresh: {len(summary['errors'])} failed fetches by endpoint "
            f"{by_endpoint}; e.g. {summary['errors'][0]['error'][:200]}"
        )
    return summary


def _restage_filings(context: OpExecutionContext, tag: str) -> None:
    """Re-merge every ticker's filings (Finnhub + SEC balance sheets) before a
    dataset build, so tickers outside the latest refresh read the current
    merge too, and log where the last year's balance sheets came from."""
    warehouse = Warehouse()
    warehouse.init_schema()
    staged = rebuild_financials_reported(warehouse)
    since = (_now().date() - timedelta(days=365)).isoformat()
    sources = balance_sheet_sources(warehouse, since)
    context.log.info(
        f"[{tag}] staged {staged} filings; balance sheets of filings since {since}: {sources}"
    )
    missing = sources.get("none", 0)
    if missing > 0.1 * sum(sources.values()):
        context.log.warning(
            f"[{tag}] {missing} recent filings have no balance sheet from Finnhub or SEC; "
            "their fundamentals are blank and those tickers drop out of the ranking"
        )


def _rebuild_dataset(context: OpExecutionContext) -> dict:
    """Rebuild train_dataset_quarterly.parquet (+ scoring cohort) from the mart."""
    from .quarterly import rebuild_quarterly_dataset

    _restage_filings(context, "dataset")
    info = rebuild_quarterly_dataset()
    context.log.info(
        f"[dataset] {info['rows']} rows, {info['tickers']} tickers; training snapshots "
        f"{info['first_training_snapshot']} -> {info['last_training_snapshot']} "
        f"(outcomes through {info['outcomes_through']}); ranking the "
        f"{info['score_snapshot']} snapshot ({info['score_tickers']} tickers); "
        f"recent snapshot sizes {info['recent_cohort_sizes']}"
    )
    stale = info["stale_price_tickers"]
    if stale:
        context.log.warning(
            f"[dataset] {len(stale)} tickers have prices more than 7 days behind "
            f"{info['newest_price']} and are left out of the ranking: "
            f"{', '.join(stale[:50])}{' ...' if len(stale) > 50 else ''}"
        )
    return info


@op(pool=WAREHOUSE_POOL)
def rebuild_dataset_op(context: OpExecutionContext, prev: dict) -> dict:
    """Rebuild the training dataset from the freshly refreshed mart."""
    return {**prev, "dataset": _rebuild_dataset(context)}


@op(pool=WAREHOUSE_POOL)
def rebuild_dataset_only_op(context: OpExecutionContext) -> dict:
    """Rebuild the training dataset from the mart as it stands (no refresh)."""
    return {"dataset": _rebuild_dataset(context)}


@op(pool=WAREHOUSE_POOL)
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


@job(name="model_retrain")
def model_retrain_job() -> None:
    """Second half of the quarterly chain: dataset rebuild -> retrain.

    Skips the hours-long universe refresh — for re-running the retrain once
    the data is already fresh (e.g. after a notebook failure).
    """
    retrain_model_op(rebuild_dataset_only_op())


@schedule(
    job=quarterly_model_refresh_job,
    cron_schedule="0 3 1 1,4,7,10 *",
    default_status=DefaultScheduleStatus.RUNNING,
)
def quarterly_schedule() -> dict:
    """03:00 UTC on the first day of each quarter (Jan/Apr/Jul/Oct)."""
    return {}


@op(required_resource_keys={"engine"}, pool=WAREHOUSE_POOL)
def weekly_refresh_op(context: OpExecutionContext) -> dict:
    """Refresh every ticker in the warehouse plus the S&P 500 benchmark.

    Same incremental runner as the quarterly refresh, except daily prices
    skip the staleness gate: the list must be built from Friday's close, and
    a ticker viewed during Friday's session would otherwise still be inside
    its 1-day price TTL.
    """
    from .weekly import weekly_universe

    engine = context.resources.engine
    universe = weekly_universe(engine.warehouse)
    context.log.info(f"weekly refresh: {len(universe)} tickers")
    summary = refresh_tickers(
        engine, universe, force_endpoints=frozenset({"prices.daily"}), log=context.log.info
    )
    if summary["errors"]:
        by_endpoint: dict[str, int] = {}
        for err in summary["errors"]:
            by_endpoint[err["endpoint"]] = by_endpoint.get(err["endpoint"], 0) + 1
        context.log.warning(
            f"weekly refresh: {len(summary['errors'])} failed fetches by endpoint "
            f"{by_endpoint}; e.g. {summary['errors'][0]['error'][:200]}"
        )
    return summary


def _rebuild_weekly_dataset(context: OpExecutionContext) -> dict:
    """Rebuild the weekly training parquet + this week's scoring cohort."""
    from .weekly import rebuild_weekly_dataset

    _restage_filings(context, "weekly dataset")
    info = rebuild_weekly_dataset()
    context.log.info(
        f"[weekly dataset] {info['rows']} rows, {info['tickers']} tickers; weeks "
        f"{info['first_week']} -> {info['last_week']}; ranking the {info['score_snapshot']} "
        f"snapshot ({info['score_tickers']} tickers, close {info['week_close']})"
    )
    for key, what in (
        ("stale_tickers", "stopped before the week's last close"),
        ("missing_tickers", "have no bars this week"),
    ):
        if info[key]:
            context.log.warning(
                f"[weekly dataset] {len(info[key])} tickers {what} and are left out: "
                f"{', '.join(info[key][:50])}{' ...' if len(info[key]) > 50 else ''}"
            )
    return info


@op(pool=WAREHOUSE_POOL)
def weekly_dataset_op(context: OpExecutionContext, prev: dict) -> dict:
    """Rebuild the weekly dataset from the freshly refreshed mart."""
    return {**prev, "dataset": _rebuild_weekly_dataset(context)}


@op(pool=WAREHOUSE_POOL)
def weekly_dataset_only_op(context: OpExecutionContext) -> dict:
    """Rebuild the weekly dataset from the mart as it stands (no refresh)."""
    return {"dataset": _rebuild_weekly_dataset(context)}


@op(pool=WAREHOUSE_POOL)
def weekly_rank_op(context: OpExecutionContext, prev: dict) -> dict:
    """Walk-forward validate, refit, rank this week's snapshot and export
    to mart.weekly_rankings (grading last week's list on the way)."""
    from .weekly import train_and_rank

    info = train_and_rank()
    context.log.info(
        f"[weekly rank] {info['as_of']}: top 10 {', '.join(info['top10'])}; walk-forward "
        f"{info['weeks']} weeks, top-10 excess {info['top10_excess'] * 1e4:+.0f} bp/week "
        f"(t={info['top10_t']:+.2f}); graded lists {info['graded_lists'] or 'none'}"
    )
    return {**prev, "rank": info}


@job(name="weekly_model_refresh")
def weekly_model_refresh_job() -> None:
    """Friday chain: universe refresh -> weekly dataset rebuild -> rank."""
    weekly_rank_op(weekly_dataset_op(weekly_refresh_op()))


@job(name="weekly_rank")
def weekly_rank_job() -> None:
    """Second half of the Friday chain: dataset rebuild -> rank.

    Skips the universe refresh — for re-running once the data is already
    fresh (e.g. after a training failure).
    """
    weekly_rank_op(weekly_dataset_only_op())


@schedule(
    job=weekly_model_refresh_job,
    cron_schedule="30 17 * * 5",
    execution_timezone="America/New_York",
    default_status=DefaultScheduleStatus.RUNNING,
)
def weekly_schedule() -> dict:
    """17:30 ET every Friday, 90 minutes after the close (New York time, so
    DST never shifts it): the list is ready well before Monday's open."""
    return {}


defs = Definitions(
    resources={"engine": engine_resource, "llm": llm_resource},
    assets=[
        ticker_data,
        stg_prices_daily,
        stg_financials_reported,
        m_prices_weekly,
        m_prices_monthly,
        m_advanced_analytics,
        m_technical_indicators,
        ticker_score,
    ],
    jobs=[
        monthly_job,
        weekdays_job,
        overnight_job,
        daily_job,
        news_job,
        daily_digest_job,
        weekly_digest_job,
        refresh_tickers_job,
        refresh_quotes_job,
        quarterly_model_refresh_job,
        model_retrain_job,
        weekly_model_refresh_job,
        weekly_rank_job,
    ],
    schedules=[
        monthly_schedule,
        weekdays_schedule,
        overnight_schedule,
        daily_schedule,
        news_morning_schedule,
        news_evening_schedule,
        daily_digest_schedule,
        weekly_digest_schedule,
        quarterly_schedule,
        weekly_schedule,
    ],
    # DuckDB is a single-writer file: with the default multiprocess executor
    # every step runs in its own subprocess and the four mart siblings (all
    # depending only on stg_prices_daily) launch concurrently and fight over
    # the write lock. In-process keeps each run's steps sequential; across
    # runs, the warehouse pool keeps scheduled jobs apart and
    # Warehouse.connect retries cover the site-triggered ones.
    executor=in_process_executor,
)
