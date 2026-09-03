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
    MOAT = "moat"
    SENTIMENT = "sentiment"
    VOLATILITY = "volatility"


@dataclass(frozen=True)
class CategoryScore:
    category: ScoreCategory
    score: float
    weight: float

    def to_dict(self) -> dict:
        return {"category": self.category.value, "score": round(self.score, 1), "weight": round(self.weight, 3)}


@dataclass(frozen=True)
class ComponentScore:
    category: ScoreCategory
    component: str
    score: float
    weight: float
    source: str

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "component": self.component,
            "score": round(self.score, 1),
            "weight": round(self.weight, 3),
            "source": self.source,
        }


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
class RankedTicker:
    rank: int
    ticker: str
    sector: str | None
    score: float | None

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "ticker": self.ticker,
            "sector": self.sector,
            "score": round(self.score, 4) if self.score is not None else None,
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
    components: tuple[ComponentScore, ...] = field(default_factory=tuple)
    buy_plan: BuyPlan | None = None
    logo_url: str | None = None
    fair_value: float | None = None
    target_price: float | None = None
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
            "components": [c.to_dict() for c in self.components],
            "buy_plan": self.buy_plan.to_dict() if self.buy_plan else None,
            "logo_url": self.logo_url,
            "fair_value": round(self.fair_value, 2) if self.fair_value else None,
            "target_price": round(self.target_price, 2) if self.target_price else None,
            "source": self.source,
        }