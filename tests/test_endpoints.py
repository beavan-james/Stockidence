"""Unit tests for the endpoint metadata registry."""

from __future__ import annotations

from datetime import timedelta

from stockidence.ingest.endpoints import (
    Cadence,
    Provider,
    REGISTRY,
    Trigger,
    endpoints_for_provider,
    get_endpoint,
    on_demand_endpoints,
    scheduled_endpoints,
)


def test_registry_names_unique():
    assert len(REGISTRY) == len({spec.name for spec in REGISTRY.values()})


def test_every_spec_has_watermark_and_artifacts():
    for spec in REGISTRY.values():
        assert spec.watermark, f"{spec.name}: missing watermark"
        assert spec.artifacts, f"{spec.name}: missing artifacts"


def test_ttl_rules_match_architecture():
    hot_path = get_endpoint("quote")
    assert hot_path.cadence == Cadence.HOT_PATH
    assert hot_path.ttl and hot_path.ttl <= timedelta(minutes=1)

    for name in ("company_profile2", "basic_financials"):
        spec = get_endpoint(name)
        assert spec.ttl and spec.ttl <= timedelta(days=7), f"{name}: TTL should be a few days"

    immutable = get_endpoint("earnings_call_transcript")
    assert immutable.cadence == Cadence.IMMUTABLE
    assert immutable.ttl is None

    for name in ("insider_sentiment", "financials_reported"):
        spec = get_endpoint(name)
        assert spec.cadence == Cadence.CONDITIONAL, f"{name}: should be conditional"
        assert spec.ttl is None, f"{name}: stale check gated by the filing, not a TTL"


def test_prices_daily_is_twelve_data():
    spec = get_endpoint("prices.daily")
    assert spec.provider == Provider.TWELVE_DATA
    assert spec.method == "time_series"
    assert "adjust=splits" in spec.notes


def test_prices_weekly_monthly_are_derived():
    for name in ("prices.weekly", "prices.monthly"):
        spec = get_endpoint(name)
        assert spec.provider == Provider.DERIVED
        assert spec.method is None
        assert spec.trigger == Trigger.DERIVED


def test_derived_have_no_api_call():
    for name in ("technical_indicators", "advanced_analytics", "prices.weekly", "prices.monthly"):
        spec = get_endpoint(name)
        assert spec.provider == Provider.DERIVED
        assert spec.method is None
        assert spec.trigger == Trigger.DERIVED


def test_scheduled_split_matches_architecture():
    names = {spec.name for spec in scheduled_endpoints()}
    assert "commodities.gold" in names
    assert "macro.cpi" in names
    assert "top_gainers_losers" in names
    assert "market_news" in names
    assert "quote" not in names


def test_on_demand_endpoints_include_hot_and_stale():
    names = {spec.name for spec in on_demand_endpoints()}
    assert "quote" in names
    assert "prices.daily" in names
    assert "company_profile2" in names
    assert "peers" in names
    assert "technical_indicators" not in names


def test_provider_filter():
    fh = {spec.name for spec in endpoints_for_provider(Provider.FINNHUB)}
    assert "quote" in fh
    assert "company_profile2" in fh
    assert "top_gainers_losers" not in fh