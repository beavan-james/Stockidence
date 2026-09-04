from __future__ import annotations

"""Per-component sub-score display spec (labels, sources, direction rules).

Mirrors the scoring engine's sub-score tables. Weights come
from the mart rows at read time, never from here; this file only carries the
human-readable provenance text (label + API source fields) and the direction
semantics so the UI can explain why a sub-score reads as buy-friendly or not.
"""

COMPONENT_SPEC: dict[str, dict[str, str]] = {
    # Valuation
    "discount_to_fair_value": {
        "label": "Discount to fair value",
        "sources": "Market cap + price vs fair value",
        "direction": "Larger gap to undervalued = higher",
    },
    "pe_percentile": {
        "label": "Historical P/E percentile",
        "sources": "Company Overview (PERatio), Daily/Weekly/Monthly + EPS history",
        "direction": "Below own 3-5yr median = cheap",
    },
    "forward_vs_trailing_pe": {
        "label": "Forward vs trailing P/E gap",
        "sources": "Company Overview (TrailingPE, ForwardPE), Earnings Estimate",
        "direction": "Forward < trailing = growth expected = positive",
    },
    "peg": {
        "label": "PEG",
        "sources": "Company Overview (PEGRatio), Earnings Estimate",
        "direction": "PEG < 1 high, 1-2 mid, > 2.5 low",
    },
    "multiple_quality": {
        "label": "Multiple quality vs own history",
        "sources": "Company Overview (P/S, EV/EBITDA, P/B, EV/Revenue), NetProfitMargin",
        "direction": "Cheap on quality vs own history",
    },
    "eps_surprise_momentum": {
        "label": "Recent EPS surprise momentum",
        "sources": "EPS Surprises (surprisePercent, last 4 quarters)",
        "direction": "Avg recent beats vs older = positive",
    },
    # Trend
    "price_vs_smas": {
        "label": "Price vs SMA50/SMA200",
        "sources": "SMA, Company Overview (50/200DMA)",
        "direction": "Price > SMA = positive; golden/death cross alignment",
    },
    "macd": {
        "label": "MACD (derived in mart)",
        "sources": "EMA12/EMA26 from Daily",
        "direction": "MACD > signal + histogram expanding = positive",
    },
    "adx_di": {
        "label": "ADX trend strength +DI/-DI",
        "sources": "ADX",
        "direction": "ADX > 25 and +DI > -DI = strong uptrend",
    },
    "rsi": {
        "label": "RSI momentum/entry",
        "sources": "RSI",
        "direction": "70+ overbought, 30-50 in uptrend = entry",
    },
    "stoch_cci": {
        "label": "Stochastic + CCI",
        "sources": "STOCH, CCI",
        "direction": "20-40 rising = positive; >80 = negative",
    },
    "volume_confirmation": {
        "label": "Volume confirmation",
        "sources": "OBV, AD",
        "direction": "OBV/AD trending with price = positive; divergence = negative",
    },
    # Sentiment
    "news_14d": {
        "label": "News sentiment (last 2 weeks)",
        "sources": "Market News + Company News (avg sentiment, -1..1)",
        "direction": "Higher avg sentiment = positive",
    },
    "analyst_consensus": {
        "label": "Analyst consensus",
        "sources": "Company Overview analyst ratings + Recommendation Trends",
        "direction": "More buy ratings = positive",
    },
    "insider": {
        "label": "Insider sentiment",
        "sources": "Insider Sentiment (mspr trend, change)",
        "direction": "Insider buying trend = positive",
    },
    "transcript_tone": {
        "label": "Earnings call transcript tone",
        "sources": "Earnings Call Transcript (avg segment sentiment)",
        "direction": "Positive call tone = positive",
    },
    "eps_surprise_trend": {
        "label": "Earnings surprise trend",
        "sources": "EPS Surprises (reused from valuation, not double-counted)",
        "direction": "Streak of beats = positive",
    },
    # Moat
    "margin_quality": {
        "label": "Margin quality",
        "sources": "Income Statement (gross/operating/net margin level + 3-5yr stability)",
        "direction": "High stable margins = positive",
    },
    "return_on_capital": {
        "label": "Return on capital",
        "sources": "Balance Sheet + Income (ROE, ROA; ROIC proxy)",
        "direction": "High ROE/ROA = positive",
    },
    "growth_consistency": {
        "label": "Growth consistency",
        "sources": "Income Statement + Monthly (revenue/EPS stability)",
        "direction": "Stable revenue/EPS growth = positive",
    },
    "scale_advantage": {
        "label": "Scale advantage",
        "sources": "Company Overview (market cap vs peer median)",
        "direction": "Above peer median size = positive",
    },
    # Volatility (separate score — higher = riskier)
    "realized_vol": {
        "label": "Realized vol",
        "sources": "Advanced Analytics (STDDEV annualized, 1yr)",
        "direction": "Lower = less risky",
    },
    "atr_pct": {
        "label": "ATR%",
        "sources": "ATR / price",
        "direction": "Lower = less risky",
    },
    "bb_bandwidth_percentile": {
        "label": "BBANDS bandwidth",
        "sources": "BBANDS bandwidth percentile vs 1yr history",
        "direction": "Lower percentile = tighter range",
    },
    "beta": {
        "label": "Beta",
        "sources": "Company Overview (Beta)",
        "direction": "Lower = less market-sensitive",
    },
}


def component_label(component: str) -> str:
    spec = COMPONENT_SPEC.get(component)
    if spec is None:
        return component.replace("_", " ").title()
    return spec["label"]


def component_sources(component: str) -> str:
    spec = COMPONENT_SPEC.get(component)
    if spec is None:
        return ""
    return spec["sources"]


def component_direction(component: str) -> str:
    spec = COMPONENT_SPEC.get(component)
    if spec is None:
        return ""
    return spec["direction"]