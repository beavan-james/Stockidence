"""Endpoint metadata registry.

One row per API-callable endpoint (and per derived table). Encodes the three
things AGENTS.md requires before writing ingestion code: cadence, watermark
key, and cache TTL. The Dagster assets that come later read this registry
rather than hardcoding schedules/parameters.

Cadence follows ARCHITECTURE.md:
  monthly / weekdays / daily  -> scheduled jobs (persistent data)
  hot-path                    -> behind the Finnhub quote cache (TTL ~1 min)
  on-demand-stale             -> fetched per ticker via the staleness gate
  immutable / conditional     -> variation of on-demand-stale
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
    DERIVED = "derived"


class Trigger(StrEnum):
    SCHEDULED = "scheduled"
    ON_DEMAND_EVERY = "on_demand_every"
    ON_DEMAND_STALE = "on_demand_stale"
    DERIVED = "derived"


class Cadence(StrEnum):
    MONTHLY = "monthly"
    WEEKDAYS = "weekdays"
    DAILY = "daily"
    HOT_PATH = "hot_path"
    IMMUTABLE = "immutable"
    CONDITIONAL = "conditional"
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
    # --- persistent: weekdays ---
    EndpointSpec(
        name="top_gainers_losers",
        provider=Provider.ALPHA_VANTAGE,
        method="top_gainers_losers",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.WEEKDAYS,
        watermark=("ticker", "date"),
        artifacts=("raw_gainers_losers",),
        ttl=timedelta(days=1),
        notes="POST-market close snapshot; one row per mover bucket",
    ),
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
        provider=Provider.ALPHA_VANTAGE,
        method="market_news",
        trigger=Trigger.SCHEDULED,
        cadence=Cadence.DAILY,
        watermark=("article_id",),
        artifacts=("raw_news_articles", "news_ticker_sentiment"),
        ttl=timedelta(days=1),
        notes="One response fans out to the article table and the ticker junction table",
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
        notes="freq=annual; staleness gated by the filing itself — refetch only "
        "if a newer accessNumber exists for that ticker, not on a day-count TTL",
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