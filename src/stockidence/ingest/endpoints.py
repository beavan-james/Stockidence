"""Endpoint metadata registry.

One row per API-callable endpoint (and per derived table). Encodes the three
things AGENTS.md requires before writing ingestion code: cadence, watermark
key, and cache TTL. The Dagster assets that come later read this registry
rather than hardcoding schedules/parameters.

Cadence follows ARCHITECTURE.md:
  monthly / weekdays / overnight / daily -> scheduled jobs (persistent data)
  hot-path                    -> behind the Finnhub quote cache (TTL ~1 min)
  on-demand-stale             -> fetched per ticker via the staleness gate
  immutable / conditional     -> variation of on-demand-stale
  gap-fill                    -> fetched only to fill a gap another source left
  event                       -> fetched inside another job, only for what that
                                 job's output names (the pages behind the
                                 stories a news digest picked)
  derived                     -> no API call, pipelined derivation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum


class Provider(StrEnum):
    ALPHA_VANTAGE = "alpha_vantage"
    FINNHUB = "finnhub"
    TWELVE_DATA = "twelve_data"
    FRED = "fred"
    SEC_EDGAR = "sec_edgar"
    # government release feeds (Fed, BLS, SEC press releases, FTC): RSS
    AGENCIES = "agencies"
    # publisher web pages, not an API: ingest.articles fetches them
    PUBLISHERS = "publishers"
    DERIVED = "derived"


class Trigger(StrEnum):
    SCHEDULED = "scheduled"
    ON_DEMAND_EVERY = "on_demand_every"
    ON_DEMAND_STALE = "on_demand_stale"
    # a step chained inside another job, not a job of its own
    CHAINED = "chained"
    DERIVED = "derived"


class Cadence(StrEnum):
    MONTHLY = "monthly"
    WEEKDAYS = "weekdays"
    OVERNIGHT = "overnight"  # after midnight, for sources that publish a session late that evening
    DAILY = "daily"
    HOT_PATH = "hot_path"
    IMMUTABLE = "immutable"
    CONDITIONAL = "conditional"
    GAP_FILL = "gap_fill"
    EVENT = "event"
    DERIVED = "derived"


@dataclass(frozen=True)
class EndpointSpec:
    """Metadata for one ingestion endpoint (API call or derived table).

    name: unique id used by assets, jobs, and the watermark store.
    provider: which client class owns the call (DERIVED means no API call).
    method: client method to invoke (None for derived tables).
    trigger: scheduled vs on-demand (every lookup vs stale-gated).
    cadence: refresh cadence label, see module docstring.
    watermark: primary key columns of the destination table — the job's
        progress unit, used for incremental loads and dedup.
    ttl: cache time-to-live; None for derived/immutable/conditional tables.
    artifacts: table(s) a single API response fans out into.
    notes: freeform card for TTL rationale / special policy.
    """

    name: str
    provider: Provider
    method: str | None
    trigger: Trigger
    cadence: Cadence
    watermark: tuple[str, ...]
    artifacts: tuple[str, ...]
    ttl: timedelta | None = None
    notes: str = ""


_REGISTRY: list[EndpointSpec] = [
    # --- persistent: monthly ---
    EndpointSpec(
        name="commodities.gold",
        provider=Provider.ALPHA_VANTAGE,
        method="gold",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("nominal", "date"),
        artifacts=("raw_commodities",),
        ttl=timedelta(days=31),
        notes="AV GOLD monthly series",
    ),
    EndpointSpec(
        name="commodities.silver",
        provider=Provider.ALPHA_VANTAGE,
        method="silver",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("nominal", "date"),
        artifacts=("raw_commodities",),
        ttl=timedelta(days=31),
        notes="AV SILVER monthly series",
    ),
    EndpointSpec(
        name="macro.inflation",
        provider=Provider.ALPHA_VANTAGE,
        method="inflation",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
        notes=("AV INFLATION is annual and frozen upstream at Jan 2024; "
               "the frontend derives current YoY from the CPI series instead"),
    ),
    EndpointSpec(
        name="macro.cpi",
        provider=Provider.ALPHA_VANTAGE,
        method="cpi",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
    ),
    EndpointSpec(
        name="macro.unemployment",
        provider=Provider.ALPHA_VANTAGE,
        method="unemployment",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
    ),
    EndpointSpec(
        name="macro.federal_funds_rate",
        provider=Provider.ALPHA_VANTAGE,
        method="federal_funds_rate",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
        notes="interval=monthly",
    ),
    EndpointSpec(
        name="macro.natural_gas",
        provider=Provider.ALPHA_VANTAGE,
        method="natural_gas",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
    ),
    EndpointSpec(
        name="macro.real_gdp_per_capita",
        provider=Provider.ALPHA_VANTAGE,
        method="real_gdp_per_capita",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("indicator", "date"),
        artifacts=("raw_macro_indicators",),
        ttl=timedelta(days=31),
    ),
    EndpointSpec(
        name="stock_symbols",
        provider=Provider.FINNHUB,
        method="stock_symbols",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.MONTHLY,
        watermark=("mic", "symbol"),
        artifacts=("raw_stock_symbols",),
        ttl=timedelta(days=31),
        notes="Finnhub /stock/symbol full listing; keyed by mic so US + others are distinct",
    ),
    # --- persistent: overnight ---
    EndpointSpec(
        name="top_gainers_losers",
        provider=Provider.ALPHA_VANTAGE,
        method="top_gainers_losers",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.OVERNIGHT,
        watermark=("ticker", "date", "bucket"),
        artifacts=("raw_gainers_losers",),
        ttl=timedelta(days=1),
        notes="a session's list, published late that evening on the free tier; "
        "date is the session (last_updated), one row per mover bucket",
    ),
    # --- persistent: weekdays ---
    EndpointSpec(
        name="ipo_calendar",
        provider=Provider.FINNHUB,
        method="ipo_calendar",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.WEEKDAYS,
        watermark=("symbol", "date"),
        artifacts=("raw_ipo_calendar",),
        ttl=timedelta(days=1),
    ),
    EndpointSpec(
        name="earnings_calendar",
        provider=Provider.FINNHUB,
        method="earnings_calendar",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.WEEKDAYS,
        watermark=("symbol", "quarter", "year"),
        artifacts=("raw_earnings_calendar",),
        ttl=timedelta(days=1),
    ),
    # --- persistent: daily ---
    EndpointSpec(
        name="market_news",
        provider=Provider.FINNHUB,
        method="general_news",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.DAILY,
        watermark=("article_id",),
        artifacts=("raw_news_articles", "news_ticker_sentiment"),
        ttl=timedelta(days=1),
        notes="Finnhub /news?category=general (latest ~100 articles, no sentiment); "
        "fans out to the article table and the ticker junction table",
    ),
    # --- persistent: daily, market-wide indexes via FRED ---
    EndpointSpec(
        name="market.vix",
        provider=Provider.FRED,
        method="observations",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.DAILY,
        watermark=("series", "date"),
        artifacts=("raw_fred_market",),
        ttl=timedelta(days=1),
        notes="FRED VIXCLS (CBOE VIX), daily close since 1990; full-series fetch "
        "upserts idempotently on (series, date)",
    ),
    EndpointSpec(
        name="market.sp500",
        provider=Provider.FRED,
        method="observations",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.DAILY,
        watermark=("series", "date"),
        artifacts=("raw_fred_market",),
        ttl=timedelta(days=1),
        notes="FRED SP500, daily S&P 500 PRICE index (no dividends); ~10y of daily "
        "history per S&P/FRED licensing agreement",
    ),
    # --- hot path ---
    EndpointSpec(
        name="quote",
        provider=Provider.FINNHUB,
        method="quote",
        trigger=Trigger.ON_DEMAND_EVERY,
        cadence=Cadence.HOT_PATH,
        watermark=("ticker",),
        artifacts=("raw_quotes",),
        ttl=timedelta(minutes=1),
    ),
    # --- on-demand per-ticker: prices via Twelve Data ---
    EndpointSpec(
        name="prices.daily",
        provider=Provider.TWELVE_DATA,
        method="time_series",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker", "date"),
        artifacts=("raw_prices_daily",),
        ttl=timedelta(days=1),
        notes="interval=1day, adjust=splits; weekly/monthly resampled downstream, not fetched",
    ),
    # --- on-demand per-ticker: fundamentals / sentiment / structure ---
    EndpointSpec(
        name="company_profile2",
        provider=Provider.FINNHUB,
        method="company_profile2",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker",),
        artifacts=("raw_company_profile",),
        ttl=timedelta(days=3),
        notes="snapshot-style; latest row per ticker",
    ),
    EndpointSpec(
        name="basic_financials",
        provider=Provider.FINNHUB,
        method="basic_financials",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker", "quarter", "year"),
        artifacts=("raw_basic_financials",),
        ttl=timedelta(days=3),
        notes="metric=all",
    ),
    EndpointSpec(
        name="financials_reported",
        provider=Provider.FINNHUB,
        method="financials_reported",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.CONDITIONAL,
        watermark=("ticker", "quarter", "year"),
        artifacts=("raw_financials_reported",),
        ttl=None,
        notes="freq=quarterly (10-Qs only); staleness gated by the filing itself — "
        "refetch only once the 10-Q after the newest one held is due, not on a day-count TTL",
    ),
    # Must stay after financials_reported: the gap check reads the filings
    # that endpoint just landed.
    EndpointSpec(
        name="sec_balance_sheets",
        provider=Provider.SEC_EDGAR,
        method="company_facts",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.GAP_FILL,
        watermark=("ticker", "accession_number"),
        artifacts=("raw_sec_balance_sheets",),
        ttl=None,
        notes="SEC companyfacts balance sheets, fetched only when Finnhub landed a "
        "filing with an empty balance sheet since the ticker's last SEC fetch; "
        "a filing never changes, so no TTL",
    ),
    EndpointSpec(
        name="eps_surprises",
        provider=Provider.FINNHUB,
        method="eps_surprises",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker", "quarter", "year"),
        artifacts=("raw_eps_surprises",),
        ttl=timedelta(days=30),
    ),
    EndpointSpec(
        name="earnings_call_transcript",
        provider=Provider.ALPHA_VANTAGE,
        method="earnings_call_transcript",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.IMMUTABLE,
        watermark=("ticker", "quarter", "year"),
        artifacts=("raw_transcript_segments",),
        ttl=None,
        notes="immutable once published; never refetch",
    ),
    EndpointSpec(
        name="ticker_news",
        provider=Provider.FINNHUB,
        method="company_news",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker",),
        artifacts=("ticker_news_fetches", "raw_news_articles", "news_ticker_sentiment"),
        ttl=timedelta(days=30),
        notes="Finnhub /company-news for the trailing year (free-tier limit); "
        "refreshes monthly on ticker lookup; ongoing freshness also "
        "comes from the daily market_news job landing into the same tables",
    ),
    EndpointSpec(
        name="insider_sentiment",
        provider=Provider.FINNHUB,
        method="insider_sentiment",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.CONDITIONAL,
        watermark=("ticker", "year", "month"),
        artifacts=("raw_insider_sentiment",),
        ttl=None,
        notes="refetch only if current month has no row",
    ),
    EndpointSpec(
        name="recommendation_trends",
        provider=Provider.FINNHUB,
        method="recommendation_trends",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker", "period"),
        artifacts=("raw_recommendation_trends",),
        ttl=timedelta(days=30),
    ),
    EndpointSpec(
        name="peers",
        provider=Provider.FINNHUB,
        method="peers",
        trigger=Trigger.ON_DEMAND_STALE,
        cadence=Cadence.MONTHLY,
        watermark=("ticker",),
        artifacts=("raw_peers",),
        ttl=timedelta(days=60),
    ),
    # --- derived: no API call ---
    EndpointSpec(
        name="prices.weekly",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("ticker", "date"),
        artifacts=("m_prices_weekly",),
        ttl=None,
        notes="weekly OHLCV resampled from raw_prices_daily",
    ),
    EndpointSpec(
        name="prices.monthly",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("ticker", "date"),
        artifacts=("m_prices_monthly",),
        ttl=None,
        notes="monthly OHLCV resampled from raw_prices_daily",
    ),
    EndpointSpec(
        name="technical_indicators",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("ticker", "date"),
        artifacts=("m_technical_indicators",),
        ttl=None,
        notes="SMA/EMA/MACD/RSI/ADX/CCI/AD/OBV/BBANDS/ATR from raw_prices_daily",
    ),
    EndpointSpec(
        name="advanced_analytics",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("ticker", "date"),
        artifacts=("m_advanced_analytics",),
        ttl=None,
        notes="MIN/MAX/MEAN/STDDEV/VARIANCE/MAX_DRAWDOWN from raw_prices_daily",
    ),
    EndpointSpec(
        name="news_articles",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("article_id",),
        artifacts=("stg_news_articles",),
        ttl=None,
        notes="both providers' raw_news_articles payloads typed into one layout; "
        "incremental, high watermark = newest staged fetched_at",
    ),
    EndpointSpec(
        name="news_digest.daily",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("period", "digest_date"),
        artifacts=("news_digests", "news_digest_stories", "news_digest_articles"),
        ttl=None,
        notes="top stories of the 24h to 07:00 New York time, from stg_news_articles; "
        "built weekdays 07:30 NY by the daily_digest job, a rebuild replaces the date",
    ),
    EndpointSpec(
        name="news_digest.weekly",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("period", "digest_date"),
        artifacts=("news_digests", "news_digest_stories", "news_digest_articles"),
        ttl=None,
        notes="top stories of the 7 days to Saturday 07:00 New York time, dated by the "
        "week's Friday; built Saturdays 07:30 NY by the weekly_digest job",
    ),
    # --- the digest's stories: primary sources only (ingest.sec_filings,
    # ingest.agency_feeds). Chained in daily_digest (weekdays 07:30 NY) and
    # weekly_digest (Saturdays 07:30 NY), right after the news pull, landing
    # into raw_news_articles in the shared payload shape. market_news stays
    # as market context and is never a story.
    EndpointSpec(
        name="sec_8k_releases",
        provider=Provider.SEC_EDGAR,
        method="current_filings",
        trigger=Trigger.CHAINED,
        cadence=Cadence.DAILY,
        watermark=("article_id",),
        artifacts=("raw_news_articles", "news_ticker_sentiment"),
        # a filing never changes once accepted
        ttl=None,
        notes="the tracked companies' 8-Ks since the pull cursor (the newest acceptance time "
        "read, held back before any filing that failed); latest-filings Atom feed, the daily "
        "form index when the cursor is older than the feed reaches; per filing the index "
        "page and the press release (EX-99.1) or the 8-K itself; one article per accession, "
        "article_id = hash of the document URL; routine items skipped; SEC_USER_AGENT, "
        "at most 5 requests a second; first run looks back 36h",
    ),
    EndpointSpec(
        name="sec_company_tickers",
        provider=Provider.SEC_EDGAR,
        method="company_tickers",
        trigger=Trigger.CHAINED,
        cadence=Cadence.MONTHLY,
        watermark=("ticker",),
        artifacts=("raw_sec_company_tickers",),
        ttl=timedelta(days=7),
        notes="SEC's ticker -> CIK list; refreshed by the 8-K pull when its one snapshot "
        "watermark is older than the TTL. Tracked companies are the tickers with prices",
    ),
    EndpointSpec(
        name="agency_releases",
        provider=Provider.AGENCIES,
        method="feed",
        trigger=Trigger.CHAINED,
        cadence=Cadence.DAILY,
        watermark=("article_id",),
        artifacts=("raw_news_articles", "news_ticker_sentiment"),
        ttl=None,
        notes="Federal Reserve monetary releases, BLS headline numbers (a new release is "
        "a new figure in its latest-numbers feed), SEC press releases, FTC competition "
        "releases; article_id = hash of the release link (BLS: link and period); "
        "robots.txt obeyed; a feed that fails is skipped for the run",
    ),
    # --- event: the pages behind the digest's stories (NEWS_SUMMARIES.md) ---
    EndpointSpec(
        name="news_article.page",
        provider=Provider.PUBLISHERS,
        method=None,
        trigger=Trigger.CHAINED,
        cadence=Cadence.EVENT,
        watermark=("url",),
        artifacts=("news_article_pages",),
        # a success is never fetched again; this is the wait before retrying
        # a transient failure (timeout, 429, 5xx, robots.txt unreachable)
        ttl=timedelta(hours=6),
        notes="fetched by the digest jobs right after selection, only for picked stories "
        "with no readable text yet; robots.txt obeyed and AI-crawler opt-outs skipped; "
        "at most 3 attempts per URL",
    ),
    EndpointSpec(
        name="news_article.text",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("url",),
        artifacts=("stg_news_article_text",),
        ttl=None,
        notes="main text of each fetched page (trafilatura), first 1,500 words; "
        "re-extracted when the extractor version changes",
    ),
    # --- the local model's summaries of those pages (NEWS_SUMMARIES.md) ---
    EndpointSpec(
        name="news_summary.card",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("story_key",),
        artifacts=("news_story_cards",),
        ttl=None,
        notes="one fact card per picked story, written by the local model (Ollama) from "
        "its article text and checked; made once, read again only when a fallback card's "
        "article arrives later",
    ),
    EndpointSpec(
        name="news_summary.text",
        provider=Provider.DERIVED,
        method=None,
        trigger=Trigger.DERIVED,
        cadence=Cadence.DERIVED,
        watermark=("period", "digest_date", "part"),
        artifacts=("news_summaries",),
        ttl=None,
        notes="the daily paragraph and the weekly article, written by the local model from "
        "the cards and checked; rewritten when the digest's stories change",
    ),
]

REGISTRY: dict[str, EndpointSpec] = {spec.name: spec for spec in _REGISTRY}


def get_endpoint(name: str) -> EndpointSpec:
    return REGISTRY[name]


def endpoints_for_provider(provider: Provider) -> list[EndpointSpec]:
    return [spec for spec in _REGISTRY if spec.provider == provider]


def scheduled_endpoints() -> list[EndpointSpec]:
    return [spec for spec in _REGISTRY if spec.trigger == Trigger.SCHEDULED]


def on_demand_endpoints() -> list[EndpointSpec]:
    return [
        spec for spec in _REGISTRY
        if spec.trigger in (Trigger.ON_DEMAND_EVERY, Trigger.ON_DEMAND_STALE)
    ]