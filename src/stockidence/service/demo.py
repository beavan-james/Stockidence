from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone

from .models import (
    Advice,
    BuyPlan,
    CategoryScore,
    ComponentScore,
    HoldingStyle,
    Rating,
    ScoreCategory,
)

PROVISIONAL_WEIGHTS: dict[str, float] = {
    "valuation": 0.52,
    "trend": 0.21,
    "sentiment": 0.21,
    "moat": 0.06,
}

# Demo mirrors the sub-score weights per category so the breakdown
# card is consistent with the live pipeline (which reads weights from mart).
PROVISIONAL_COMPONENT_WEIGHTS: dict[str, dict[str, float]] = {
    "valuation": {
        "discount_to_fair_value": 0.40,
        "pe_percentile": 0.20,
        "forward_vs_trailing_pe": 0.10,
        "peg": 0.15,
        "multiple_quality": 0.10,
        "eps_surprise_momentum": 0.05,
    },
    "trend": {
        "price_vs_smas": 0.30,
        "macd": 0.20,
        "adx_di": 0.15,
        "rsi": 0.15,
        "stoch_cci": 0.10,
        "volume_confirmation": 0.10,
    },
    "sentiment": {
        "news_14d": 0.30,
        "analyst_consensus": 0.25,
        "insider": 0.20,
        "transcript_tone": 0.15,
        "eps_surprise_trend": 0.10,
    },
    "moat": {
        "margin_quality": 0.35,
        "return_on_capital": 0.30,
        "growth_consistency": 0.20,
        "scale_advantage": 0.15,
    },
}

_KNOWN_PRICES: dict[str, float] = {
    "AAPL": 232.5,
    "GOOGL": 176.8,
    "AMZN": 221.4,
    "META": 612.0,
    "APP": 218.3,
}

_COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com Inc.",
    "META": "Meta Platforms Inc.",
    "APP": "AppLovin Corp.",
}


def _score(seed: str) -> float:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _rng(ticker: str) -> random.Random:
    return random.Random(hashlib.sha256(ticker.encode()).hexdigest())


def _advice_from_confidence(score: float) -> Advice:
    if score >= 75:
        return Advice.STRONG_BUY
    if score >= 60:
        return Advice.BUY
    if score >= 40:
        return Advice.HOLD
    if score >= 25:
        return Advice.SELL
    return Advice.STRONG_SELL


def _holding_style(volatility: float) -> HoldingStyle:
    if volatility < 25:
        return HoldingStyle.LONG_TERM
    if volatility < 60:
        return HoldingStyle.SWING
    return HoldingStyle.DAY


def generate_rating(ticker: str) -> Rating:
    ticker = ticker.upper()
    rng = _rng(ticker)

    weights = PROVISIONAL_WEIGHTS
    purchase_price = _KNOWN_PRICES.get(ticker, round(rng.uniform(20, 400), 2))
    company = _COMPANY_NAMES.get(ticker, f"{ticker} (demo)")

    categories = tuple(
        CategoryScore(
            category=ScoreCategory(slug),
            score=10 + (_score(f"{ticker}:{slug}") * 85),
            weight=weights[slug],
        )
        for slug in weights
    )

    components = []
    for slug, sub_weights in PROVISIONAL_COMPONENT_WEIGHTS.items():
        for name in sub_weights:
            components.append(
                ComponentScore(
                    category=ScoreCategory(slug),
                    component=name,
                    score=10 + (_score(f"{ticker}:{slug}:{name}") * 85),
                    weight=sub_weights[name],
                    source="demo",
                )
            )

    confidence = sum(c.score * c.weight for c in categories)
    advice = _advice_from_confidence(confidence)

    # Deterministic demo stand-ins for the live mart outputs (fair value and
    # the 12-month target are always computed in the pipeline, buy or not).
    fair_value = round(purchase_price * (0.9 + 0.3 * _score(f"{ticker}:fair_value")), 2)
    target_price = round(fair_value * (1.0 + 0.1 * _score(f"{ticker}:target")), 2)

    volatility = _score(f"{ticker}:volatility") * 95 + 5

    buy_plan = None
    if advice in (Advice.STRONG_BUY, Advice.BUY):
        buy_price = round(purchase_price * 0.995, 2)
        stop_loss = round(buy_price * (1 - (0.02 + 0.0025 * volatility)), 2)
        buy_plan = BuyPlan(
            advised_buy_price=buy_price,
            stop_loss_price=stop_loss,
            holding_style=_holding_style(volatility),
        )

    return Rating(
        ticker=ticker,
        company_name=company,
        as_of=datetime.now(timezone.utc),
        confidence_score=confidence,
        advice=advice,
        volatility_score=volatility,
        categories=categories,
        components=tuple(components),
        buy_plan=buy_plan,
        fair_value=fair_value,
        target_price=target_price,
        source="demo",
    )