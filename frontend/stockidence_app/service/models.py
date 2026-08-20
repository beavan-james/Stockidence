from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Advice(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class HoldingStyle(StrEnum):
    LONG_TERM = "long_term_hold"
    SWING = "swing_trade"
    DAY = "day_trade"


class ScoreCategory(StrEnum):
    VALUATION = "valuation"
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    MOAT = "moat"
    SENTIMENT = "sentiment"


@dataclass(frozen=True)
class CategoryScore:
    category: ScoreCategory
    score: float
    weight: float

    def to_dict(self) -> dict:
        return {"category": self.category.value, "score": round(self.score, 1), "weight": round(self.weight, 3)}


@dataclass(frozen=True)
class BuyPlan:
    advised_buy_price: float
    stop_loss_price: float
    holding_style: HoldingStyle

    def to_dict(self) -> dict:
        return {
            "advised_buy_price": round(self.advised_buy_price, 2),
            "stop_loss_price": round(self.stop_loss_price, 2),
            "holding_style": self.holding_style.value,
        }


@dataclass(frozen=True)
class Rating:
    ticker: str
    company_name: str
    as_of: datetime
    confidence_score: float
    advice: Advice
    volatility_score: float
    categories: tuple[CategoryScore, ...] = field(default_factory=tuple)
    buy_plan: BuyPlan | None = None
    source: str = "demo"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "as_of": self.as_of.isoformat(),
            "confidence_score": round(self.confidence_score, 1),
            "advice": self.advice.value,
            "volatility_score": round(self.volatility_score, 1),
            "categories": [c.to_dict() for c in self.categories],
            "buy_plan": self.buy_plan.to_dict() if self.buy_plan else None,
            "source": self.source,
        }