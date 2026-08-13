from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone

from .models import Advice, BuyPlan, CategoryScore, HoldingStyle, Rating, ScoreCategory

PROVISIONAL_WEIGHTS: dict[str, float] = {
    "valuation": 0.40,
    "trend": 0.25,
    "momentum": 0.15,
    "sentiment": 0.20,
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
    if score >= 45:
        return Advice.HOLD
    if score >= 30:
        return Advice.SELL
    return Advice.STRONG_SELL


def _holding_style(volatility: float) -> HoldingStyle:
    if volatility < 30:
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

    confidence = sum(c.score * c.weight for c in categories)
    advice = _advice_from_confidence(confidence)

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
        buy_plan=buy_plan,
        source="demo",
    )