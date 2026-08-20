"""Deterministic scoring layer: reads raw/staging/mart, emits per-ticker
confidence rating + volatility score + fair value + buy plan.

MODEL.md is the governing spec; every weight/threshold here is a provisional
constant (centralized below) so backtesting can tune without touching logic.

Gap policy: when a sub-score's inputs are missing we degrade — a defensible
proxy substitutes (source="proxy") or the sub-score is neutral 50
(source="neutral"); live inputs score normally (source="live").
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from ..storage import Warehouse

# ---------------------------------------------------------------------------
# Model configuration (provisional per MODEL.md — tune here, not in logic)
# ---------------------------------------------------------------------------

CONFIDENCE_WEIGHTS: dict[str, float] = {
    "valuation": 0.52,
    "trend": 0.21,
    "sentiment": 0.21,
    "moat": 0.06,
}

# (minimum confidence, rating) — descending; confidence is on a 0..100 scale
RATING_BANDS: list[tuple[float, str]] = [
    (75.0, "Strong Buy"),
    (60.0, "Buy"),
    (40.0, "Hold"),
    (25.0, "Sell"),
]
FALLBACK_RATING = "Strong Sell"

VALUATION_OVERRIDE: dict[str, Any] = {
    "below": 35.0,  # valuation score below → cap rating at Hold
    "above": 70.0,  # valuation score above → floor rating at Hold
    "rating": "Hold",
}

FAIR_VALUE: dict[str, Any] = {
    "dcf_weight": 0.5,
    "risk_free_rate": 0.04,
    "equity_risk_premium": 0.05,
    "terminal_growth": 0.02,
    "growth_cap": 0.20,
    "forecast_years": 5,
    "growth_clamp": (-0.20, 0.30),
    "clamp_multiplier": 2.0,  # never more than this × current price
    "clamp_floor_scale": 0.5,
}

BUY_PLAN: dict[str, Any] = {
    "margin_of_safety": 0.15,
    "atr_multiplier": {"day trade": 1.0, "swing trade": 1.5, "long-term hold": 2.0},
    "stop_floor_scale": 0.6,  # stop never below this × buy price
}

VOLATILITY_BANDS: list[tuple[str, float | None]] = [
    ("long-term hold", 25.0),
    ("swing trade", 60.0),
    ("day trade", None),
]

# Sub-score weights within each category (MODEL.md tables)
VALUATION_SUB_WEIGHTS: dict[str, float] = {
    "discount_to_fair_value": 0.40,
    "pe_percentile": 0.20,
    "forward_vs_trailing_pe": 0.10,
    "peg": 0.15,
    "multiple_quality": 0.10,
    "eps_surprise_momentum": 0.05,
}
TREND_SUB_WEIGHTS: dict[str, float] = {
    "price_vs_smas": 0.30,
    "macd": 0.20,
    "adx_di": 0.15,
    "rsi": 0.15,
    "stoch_cci": 0.10,
    "volume_confirmation": 0.10,
}
SENTIMENT_SUB_WEIGHTS: dict[str, float] = {
    "news_14d": 0.30,
    "analyst_consensus": 0.25,
    "insider": 0.20,
    "transcript_tone": 0.15,
    "eps_surprise_trend": 0.10,
}
MOAT_SUB_WEIGHTS: dict[str, float] = {
    "margin_quality": 0.35,
    "return_on_capital": 0.30,
    "growth_consistency": 0.20,
    "scale_advantage": 0.15,
}
VOLATILITY_SUB_WEIGHTS: dict[str, float] = {
    "realized_vol": 0.30,
    "atr_pct": 0.30,
    "bb_bandwidth_percentile": 0.25,
    "beta": 0.15,
}

NEWS_WINDOW_DAYS = 14

# Tiny deterministic lexicon for transcript tone (AV transcripts carry no
# sentiment field). Common earnings-call words, weights in [-1, 1].
_TRANSCRIPT_WORDS: dict[str, float] = {
    "strong": 0.4, "record": 0.5, "growth": 0.4, "grew": 0.4, "improved": 0.3,
    "outpaced": 0.3, "momentum": 0.3, "accelerat": 0.4, "balance": 0.2,
    "opportunity": 0.3, "confident": 0.4, "guidance": 0.2, "raise": 0.3,
    "beat": 0.4, "exceed": 0.4, "positive": 0.4,
    "challeng": -0.3, "declin": -0.4, "weaker": -0.3, "decrease": -0.3,
    "volatility": -0.2, "risk": -0.3, "uncertainty": -0.3, "headwind": -0.4,
    "pressure": -0.3, "miss": -0.3, "cut": -0.3,
    "restructur": -0.2, "layoff": -0.4, "impairment": -0.3, "advers": -0.3,
    "concern": -0.3, "weak": -0.3, "lower": -0.2, "delay": -0.2,
}

# XBRL concept synonyms (financials-reported tags vary by company)
_CF_OCF = ("OperatingCashFlow", "NetCashProvidedByUsedInOperatingActivities",
           "CashGeneratedFromOperatingActivities")
_CF_CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures",
             "PaymentsForPropertyPlantAndEquipment")
_IS_REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
               "SalesRevenueNet")
_IS_NET_INCOME = ("NetIncomeLoss", "ProfitLoss", "NetIncome")
_BS_LIABILITIES = ("TotalLiabilities", "Liabilities")
_BS_CASH = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments",
            "CashAndCashEquivalents")
_BS_EQUITY = ("StockholdersEquity",
              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _num(value: Any) -> float | None:
    """Coerce API numbers (Finnhub floats, AV strings like '1.23e9')."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.fmean(vals) if vals else None


def _percentile_of(value: float, history: list[float]) -> float | None:
    """Rank of value within its own history, 0..100 (100 = highest ever)."""
    if not history:
        return None
    lo = sum(1 for h in history if h < value)
    eq = sum(1 for h in history if h == value)
    return 100.0 * (lo + 0.5 * eq) / len(history)


def _growth_to_score(growth: float | None) -> float | None:
    """Forward-vs-trailing earnings growth → 0..100 (expecting growth = good)."""
    if growth is None or not math.isfinite(growth):
        return None
    return _clamp(50.0 + growth * 150.0, 5.0, 95.0)


def _peg_to_score(peg: float | None) -> float | None:
    if peg is None or not math.isfinite(peg):
        return None
    if peg <= 1.0:
        return 82.0
    if peg <= 2.0:
        return 55.0
    if peg <= 2.5:
        return 40.0
    return 20.0


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

def _fetch_raw(con: Any, table: str, where: str, args: list[Any],
               order: str = "") -> list[dict[str, Any]]:
    """All rows of a raw table as dicts (key columns + parsed payload)."""
    cur = con.execute(
        f'SELECT * FROM raw."{table}" WHERE {where} {order}',
        args,
    )
    cols = [d[0] for d in cur.description]
    out: list[dict[str, Any]] = []
    for raw in cur.fetchall():
        row = dict(zip(cols, raw))
        payload = row.pop("payload")
        row["payload"] = json.loads(payload) if not isinstance(
            payload, dict) else payload
        out.append(row)
    return out


def _fetch_one(con: Any, table: str, where: str, args: list[Any]) -> dict[str, Any] | None:
    rows = _fetch_raw(con, table, where, args)
    return rows[-1] if rows else None


def _eps_surprise_rows(con: Any, ticker: str) -> list[dict[str, Any]]:
    return _fetch_raw(con, "raw_eps_surprises", "ticker = ?", [ticker],
                      "ORDER BY year, quarter")


def _reported_rows(con: Any, ticker: str) -> list[dict[str, Any]]:
    """Fiscal-period rows, oldest first (approximation for fiscal ordering)."""
    return _fetch_raw(con, "raw_financials_reported", "ticker = ?", [ticker],
                      "ORDER BY year, quarter")


def _basic_rows(con: Any, ticker: str) -> list[dict[str, Any]]:
    return _fetch_raw(con, "raw_basic_financials", "ticker = ?", [ticker],
                      "ORDER BY year, quarter")


@dataclass(frozen=True)
class Component:
    """One sub-score with provenance for the frontend."""
    category: str
    name: str
    value: float
    weight: float
    source: str


@dataclass(frozen=True)
class CategoryScore:
    name: str
    score: float
    components: list[Component] = field(default_factory=list)


@dataclass(frozen=True)
class ScoreResult:
    ticker: str
    computed_at: datetime
    confidence_score: float
    rating: str
    categories: list[CategoryScore]
    volatility_score: float
    volatility_components: list[Component]
    fair_value: float | None
    target_price: float | None
    fair_value_sources: list[str] = field(default_factory=list)
    valuation_override_applied: bool = False
    buy_plan: dict[str, Any] | None = None  # {price, stop_loss, holding_style}


def _category_score(name: str, weights: dict[str, float], components: list[Component]) -> CategoryScore:
    """Weighted blend of a category's components; missing sub-scores count
    as neutral 50 so a sparse profile degrades toward 50, never to 0."""
    present = {c.name: c for c in components}
    total_w = sum(w for n, w in weights.items() if n in present)
    if total_w == 0:
        return CategoryScore(name=name, score=50.0, components=components)
    score = sum(weights[n] * (present[n].value if n in present else 50.0)
                for n in weights)
    return CategoryScore(name=name, score=score, components=components)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

def _trailing_eps(rows: list[dict[str, Any]]) -> float | None:
    actuals = [_num(r["payload"].get("actual")) for r in rows]
    actuals = [a for a in actuals if a is not None and a > 0]
    return _mean(actuals[-4:]) if actuals else None


def _forward_eps(con: Any, ticker: str) -> float | None:
    """Next EPS estimate (earnings calendar), annualized x4."""
    rows = _fetch_raw(con, "raw_earnings_calendar", "symbol = ?", [ticker],
                      "ORDER BY year, quarter")
    est = [_num(r["payload"].get("epsEstimate")) for r in rows]
    est = [e for e in est if e is not None and e > 0]
    return est[-1] * 4.0 if est else None


def _eps_growth(con: Any, ticker: str, rows: list[dict[str, Any]]) -> float | None:
    """Forward vs trailing annualized EPS growth (both on a per-year basis)."""
    trailing = _trailing_eps(rows)  # quarterly mean → annualize with *4
    fwd = _forward_eps(con, ticker)  # quarterly estimate, already *4
    if trailing and trailing > 0 and fwd:
        return fwd / (trailing * 4.0) - 1.0
    return None


def _pe_of(price: float, eps: float) -> float | None:
    return price / (eps * 4.0) if eps and eps > 0 and price > 0 else None


def _eps_pe_history(price: float, rows: list[dict[str, Any]]) -> list[float]:
    """P/E band from quarterly actual EPS (annualized) at today's price."""
    pes: list[float] = []
    for r in rows:
        eps = _num(r["payload"].get("actual"))
        pe = _pe_of(price, eps) if eps else None
        if pe is not None:
            pes.append(pe)
    return pes


_METRIC_ALIASES = {
    # MODEL.md metric name -> Finnhub /stock/metric name. The API's series are
    # period-keyed; its scalar `metric` dict is landed at the sentinel period
    # (quarter=0/year=0) with freq "latest".
    "salesPerShareTTM": "revenuePerShareTTM",
    "returnOnEquityTTM": "roeTTM",
    "gGrowth": "epsGrowth3Y",
    "evToEBITDA": "evEbitdaTTM",
}


def _resolve_metric(name: str) -> str:
    return _METRIC_ALIASES.get(name, name)


def _current_ps(price: float, basic: list[dict[str, Any]]) -> float | None:
    rps = _latest_series(basic, "salesPerShareTTM")
    return price / rps if rps and rps > 0 and price > 0 else None


def _ps_history(price: float, basic: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    metric = _resolve_metric("salesPerShareTTM")
    for r in basic:
        if r["payload"].get("freq") != "quarterly" or r["payload"].get("metric") != metric:
            continue
        rps = _num(r["payload"].get("v"))
        if rps and rps > 0:
            out.append(price / rps)
    return out


def _latest_series(basic: list[dict[str, Any]], metric: str) -> float | None:
    """Latest value of a per-period metric (rows ordered by period asc)."""
    vals = [_num(r["payload"].get("v")) for r in basic
            if r["payload"].get("metric") == _resolve_metric(metric)]
    return vals[-1] if vals else None


def _latest_metric(basic: list[dict[str, Any]], key: str) -> float | None:
    vals = [_num(r["payload"].get("v"))
            for r in basic if r["payload"].get("metric") == _resolve_metric(key)]
    return vals[-1] if vals else None


def _valuation_components(con: Any, ticker: str, rows: list[dict[str, Any]],
                          price: float, fair: float | None) -> list[Component]:
    trailing = _trailing_eps(rows)
    growth = _eps_growth(con, ticker, rows)
    components: list[Component] = []

    # 1. discount to fair value (40%)
    if fair is not None and price > 0:
        score = _clamp(50.0 + (1.0 - price / fair) * 100.0, 0.0, 100.0)
        components.append(
            Component("valuation", "discount_to_fair_value", score, 0.40, "live"))
    else:
        components.append(
            Component("valuation", "discount_to_fair_value", 50.0, 0.40, "neutral"))

    # 2. historical P/E percentile (20%) — cheap vs its own band = good
    basic = _basic_rows(con, ticker)
    pes = _eps_pe_history(price, rows)
    cur_pe = _pe_of(price, trailing) if trailing else None
    pct = _percentile_of(cur_pe, pes) if (pes and cur_pe is not None) else None
    components.append(Component("valuation", "pe_percentile",
                                (100.0 - pct) if pct is not None else 50.0, 0.20,
                                "live" if pct is not None else "neutral"))

    # 3. forward vs trailing P/E gap (10%)
    s = _growth_to_score(growth)
    components.append(Component("valuation", "forward_vs_trailing_pe",
                                s if s is not None else 50.0, 0.10,
                                "live" if s is not None else "neutral"))

    # 4. PEG (15%) — trailing P/E / expected growth (growth in % units)
    pe = _pe_of(price, trailing) if trailing else None
    peg = pe / (growth * 100.0) if (pe and growth and growth > 0) else None
    s = _peg_to_score(peg)
    components.append(Component("valuation", "peg",
                                s if s is not None else 50.0, 0.15,
                                "live" if s is not None else "neutral"))

    # 5. multiple quality vs own history (10%) — P/S percentile + margin lift
    ps_hist = _ps_history(price, basic)
    ps_pct = _percentile_of(_current_ps(price, basic), ps_hist) if (
        ps_hist and _current_ps(price, basic) is not None) else None
    margin = _latest_series(basic, "netMargin")
    margin_score = _clamp(25.0 + (margin or 0.0) * 300.0,
                          0.0, 95.0) if margin is not None else 50.0
    if ps_pct is not None:
        score = 0.6 * (100.0 - ps_pct) + 0.4 * margin_score
        components.append(
            Component("valuation", "multiple_quality", score, 0.10, "live"))
    else:
        components.append(
            Component("valuation", "multiple_quality", 50.0, 0.10, "neutral"))

    # 6. recent EPS surprise momentum (5%)
    recent = _mean([_num(r["payload"].get("surprisePercent"))
                   for r in rows[-4:]])
    prior = _mean([_num(r["payload"].get("surprisePercent"))
                  for r in rows[-8:-4]])
    if recent is not None and prior is not None:
        score = _clamp(50.0 + (recent - prior) * 12.0, 0.0, 100.0)
        components.append(
            Component("valuation", "eps_surprise_momentum", score, 0.05, "live"))
    else:
        components.append(
            Component("valuation", "eps_surprise_momentum", 50.0, 0.05, "neutral"))
    return components


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def _trend_components(con: Any, ticker: str, price: float | None) -> list[Component]:
    # m_technical_indicators carries no close column (it's an adjacency join
    # on stg_prices_daily); closes for the volume window come from staging.
    cols = ("sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "macd",
            "macd_signal", "macd_hist", "rsi_14", "atr_14", "adx_14",
            "plus_di_14", "minus_di_14", "stoch_k_14", "stoch_d_14", "cci_20",
            "ad", "obv")
    rows = con.execute(
        f"""
        SELECT {", ".join(cols)}
        FROM mart.m_technical_indicators
        WHERE ticker = ? ORDER BY date
        """,
        [ticker],
    ).fetchall()
    neutral = [
        Component("trend", "price_vs_smas", 50.0, 0.30, "neutral"),
        Component("trend", "macd", 50.0, 0.20, "neutral"),
        Component("trend", "adx_di", 50.0, 0.15, "neutral"),
        Component("trend", "rsi", 50.0, 0.15, "neutral"),
        Component("trend", "stoch_cci", 50.0, 0.10, "neutral"),
        Component("trend", "volume_confirmation", 50.0, 0.10, "neutral"),
    ]
    if len(rows) < 2:
        return neutral
    last, prev = rows[-1], rows[-2]
    sma20, sma50, sma200 = last[0], last[1], last[2]
    ema12, ema26 = last[3], last[4]
    macd, macd_signal, hist, prev_hist = last[5], last[6], last[7], prev[7]
    rsi14, atr14, adx14 = last[8], last[9], last[10]
    plus_di, minus_di = last[11], last[12]
    stoch_k, stoch_d, prev_k, cci20 = last[13], last[14], prev[13], last[15]
    ad, obv = last[16], last[17]
    components: list[Component] = []

    # 1. price vs SMA50/SMA200 (30%)
    if sma50 and sma200 and price:
        prem50, prem200 = price / sma50 - 1.0, price / sma200 - 1.0
        score = 50.0
        score += math.copysign(15.0, prem50) * min(1.0, abs(prem50) * 400.0)
        score += math.copysign(12.0, prem200) * min(1.0, abs(prem200) * 400.0)
        if price > sma50 > sma200:
            score += 6.0
        components.append(Component("trend", "price_vs_smas",
                          _clamp(score, 0, 100), 0.30, "live"))
    else:
        components.append(
            Component("trend", "price_vs_smas", 50.0, 0.30, "neutral"))

    # 2. MACD (20%) — sign + histogram expansion
    if hist is not None and prev_hist is not None:
        score = 50.0 + 35.0 * math.copysign(1.0, hist)
        score += 15.0 if hist > prev_hist else (-15.0 if hist <
                                                prev_hist else 0.0)
        if macd and macd_signal and macd > 0 and macd_signal > 0:
            score += 6.0
        components.append(
            Component("trend", "macd", _clamp(score, 0, 100), 0.20, "live"))
    else:
        components.append(Component("trend", "macd", 50.0, 0.20, "neutral"))

    # 3. ADX +DI/-DI (15%)
    if adx14 is not None and plus_di is not None and minus_di is not None:
        if adx14 > 25:
            strength = min(1.0, (adx14 - 25.0) / 25.0)
            score = 72.0 + 23.0 * strength if plus_di > minus_di else 28.0 - 23.0 * strength
        else:
            score = 50.0
        components.append(Component("trend", "adx_di",
                          _clamp(score, 0, 100), 0.15, "live"))
    else:
        components.append(Component("trend", "adx_di", 50.0, 0.15, "neutral"))

    # 4. RSI (15%) — mean-reverting; 30-50 in an uptrend is the buy zone
    if rsi14 is not None:
        if rsi14 <= 20:
            score = 30.0
        elif rsi14 <= 30:
            score = 40.0
        elif rsi14 <= 50:
            score = 72.0 if (sma50 and price and price > sma50) else 55.0
        elif rsi14 <= 60:
            score = 62.0
        elif rsi14 <= 70:
            score = 45.0
        else:
            score = 25.0
        components.append(Component("trend", "rsi", score, 0.15, "live"))
    else:
        components.append(Component("trend", "rsi", 50.0, 0.15, "neutral"))

    # 5. Stochastic + CCI (10%)
    if stoch_k is not None and cci20 is not None:
        k_score = 75.0 if (stoch_k < 20 and prev_k is not None and
                           stoch_k > prev_k) else (
            30.0 if stoch_k > 80 else (45.0 if stoch_k < 20 else 60.0))
        cci_score = 65.0 if cci20 > 100 else (30.0 if cci20 < -100 else 55.0)
        components.append(Component("trend", "stoch_cci",
                          (k_score + cci_score) / 2, 0.10, "live"))
    else:
        components.append(
            Component("trend", "stoch_cci", 50.0, 0.10, "neutral"))

    # 6. Volume confirmation (10%) — OBV/AD slope vs close slope, last ~20 bars
    window = rows[-21:]
    closes = [r[0] for r in con.execute(
        "SELECT close FROM staging.stg_prices_daily WHERE ticker = ? ORDER BY date DESC LIMIT 21",
        [ticker]).fetchall()][::-1]
    ad_hist = [r[16] for r in window]
    obv_hist = [r[17] for r in window]

    def _slope(vals: list[float | None]) -> float | None:
        clean = [v for v in vals if v is not None]
        return clean[-1] - clean[0] if len(clean) >= 10 else None

    if len(window) >= 10 and len(closes) >= 10:
        close_s = _slope(closes)
        agree = [s for s in (_slope(ad_hist), _slope(obv_hist))
                 if s is not None and close_s is not None and s * close_s > 0]
        total = [s for s in (_slope(ad_hist), _slope(obv_hist))
                 if s is not None and close_s is not None]
        if total:
            score = 30.0 if not agree else 80.0
            components.append(
                Component("trend", "volume_confirmation", score, 0.10, "live"))
        else:
            components.append(
                Component("trend", "volume_confirmation", 50.0, 0.10, "neutral"))
    else:
        components.append(
            Component("trend", "volume_confirmation", 50.0, 0.10, "neutral"))
    return components


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

def _news_components(con: Any, ticker: str) -> list[Component]:
    components: list[Component] = []
    cutoff = (int(datetime.now(timezone.utc).timestamp() * 1000)
              - NEWS_WINDOW_DAYS * 86_400_000)

    # 1. news sentiment, last 14 days (30%)
    rows = con.execute(
            """
            SELECT ts.payload, a.payload
            FROM raw.news_ticker_sentiment ts
            JOIN raw.raw_news_articles a USING (article_id)
            WHERE ts.ticker = ?
            """,
            [ticker],
        ).fetchall()
    scores: list[float] = []
    for ts_raw, a_raw in rows:
        ts = json.loads(ts_raw) if not isinstance(ts_raw, dict) else ts_raw
        art = json.loads(a_raw) if not isinstance(a_raw, dict) else a_raw
        dt = _num(art.get("datetime"))
        if dt is None or dt < cutoff:
            continue
        s = _num(ts.get("ticker_sentiment_score"))
        if s is not None and abs(s) <= 1.0:
            scores.append(s)
    if scores:
        avg = statistics.fmean(scores)
        components.append(Component("sentiment", "news_14d",
                                    _clamp(50.0 + avg * 60.0, 0.0, 100.0), 0.30, "live"))
    else:
        components.append(
            Component("sentiment", "news_14d", 50.0, 0.30, "neutral"))

    # 2. analyst consensus (25%)
    rows = _fetch_raw(con, "raw_recommendation_trends", "ticker = ?", [ticker],
                      "ORDER BY period")
    score = None
    if rows:
        r = rows[-1]["payload"]
        counts = {k: (_num(r.get(k)) or 0)
                  for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        n = sum(counts.values())
        if n:
            w = (5 * counts["strongBuy"] + 4 * counts["buy"] + 3 * counts["hold"]
                 + 2 * counts["sell"] + 1 * counts["strongSell"])
            score = (w / n - 1.0) / 4.0 * 100.0
    components.append(Component("sentiment", "analyst_consensus",
                                score if score is not None else 50.0, 0.25,
                                "live" if score is not None else "neutral"))

    # 3. insider sentiment (20%) — mspr level + recent trend
    rows = _fetch_raw(con, "raw_insider_sentiment", "ticker = ?", [ticker],
                      "ORDER BY year, month")

    def _mspr(rs: list[dict[str, Any]]) -> float | None:
        return _mean([_num(r["payload"].get("mspr")) for r in rs])
    if len(rows) >= 2:
        split = max(1, len(rows) // 2)
        recent, prior = _mspr(rows[-split:]), _mspr(rows[:-split])
        if recent is not None:
            slope = (recent - prior) if prior is not None else 0.0
            score = _clamp(50.0 + recent * 50.0 + slope * 25.0, 0.0, 100.0)
            components.append(
                Component("sentiment", "insider", score, 0.20, "live"))
        else:
            components.append(
                Component("sentiment", "insider", 50.0, 0.20, "neutral"))
    else:
        components.append(
            Component("sentiment", "insider", 50.0, 0.20, "neutral"))

    # 4. transcript tone (15%) — naive lexicon on latest quarter
    segs = _fetch_raw(con, "raw_transcript_segments", "ticker = ?", [ticker],
                      "ORDER BY year, quarter, speaker_sequence")
    latest: list[dict[str, Any]] = []
    if segs:
        key = (segs[-1]["year"], segs[-1]["quarter"])
        latest = [r for r in segs if (r["year"], r["quarter"]) == key]
    tones = [_transcript_tone(r["payload"].get("content") or "") for r in latest
             if r["payload"].get("content")]
    if tones:
        tone = _mean(tones)
        components.append(
            Component("sentiment", "transcript_tone", tone * 100.0, 0.15, "live"))
    else:
        components.append(
            Component("sentiment", "transcript_tone", 50.0, 0.15, "neutral"))

    # 5. EPS surprise trend (10%) — same inputs as valuation #6
    rows = _eps_surprise_rows(con, ticker)
    recent = _mean([_num(r["payload"].get("surprisePercent"))
                   for r in rows[-4:]])
    prior = _mean([_num(r["payload"].get("surprisePercent"))
                  for r in rows[-8:-4]])
    if recent is not None and prior is not None:
        score = _clamp(50.0 + (recent - prior) * 12.0, 0.0, 100.0)
        components.append(
            Component("sentiment", "eps_surprise_trend", score, 0.10, "live"))
    else:
        components.append(
            Component("sentiment", "eps_surprise_trend", 50.0, 0.10, "neutral"))
    return components


def _transcript_tone(text: str) -> float:
    """Lexicon tone in [0, 1]; 0.5 = neutral. Deterministic, no LLM."""
    lower = text.lower()
    total = hits = 0.0
    for word, w in _TRANSCRIPT_WORDS.items():
        if word in lower:
            total += w
            hits += 1
    if not hits:
        return 0.5
    return _clamp(total / hits * 0.5 + 0.5, 0.1, 0.9)


# ---------------------------------------------------------------------------
# Moat
# ---------------------------------------------------------------------------

def _moat_components(con: Any, ticker: str) -> list[Component]:
    components: list[Component] = []
    basic = _basic_rows(con, ticker)
    reported = _reported_rows(con, ticker)

    # 1. margin quality (35%) — level + stability over last 3 fiscal years
    margins = [_num(r["payload"].get("v")) for r in basic
               if r["payload"].get("freq") == "annual"
               and r["payload"].get("metric") == "netMargin"]
    margins = [m for m in margins if m is not None]
    if len(margins) >= 2:
        mean_m = statistics.fmean(margins)
        cv = statistics.pstdev(margins) / abs(mean_m) if mean_m else 1.0
        stability = 10.0 if cv < 0.3 else (-10.0 if cv > 0.5 else 0.0)
        score = _clamp(25.0 + mean_m * 300.0 + stability, 0.0, 100.0)
        components.append(
            Component("moat", "margin_quality", score, 0.35, "live"))
    else:
        components.append(
            Component("moat", "margin_quality", 50.0, 0.35, "neutral"))

    # 2. return on capital (30%) — TTM ROE from metrics, else reported
    roe = _latest_series(basic, "returnOnEquityTTM")
    if roe is None and reported:
        latest = _reported_concepts(reported[-1]["payload"])
        ni = next((_num(d.get("value"))
                  for d in latest if d.get("concept") in _IS_NET_INCOME), None)
        eq = next((_num(d.get("value"))
                  for d in latest if d.get("concept") in _BS_EQUITY), None)
        if ni is not None and eq and eq > 0:
            roe = ni / eq
    if roe is not None:
        # ROE ~1.5+ on heavily bought-back names; linear on the ratio
        components.append(Component("moat", "return_on_capital",
                                    _clamp(roe * 90.0, 0.0, 100.0), 0.30, "live"))
    else:
        components.append(
            Component("moat", "return_on_capital", 50.0, 0.30, "neutral"))

    # 3. growth consistency (20%) — share of YoY revenue periods with growth
    revenues: dict[tuple[Any, Any], float] = {}
    for r in reported:
        rev = next((_num(d.get("value")) for d in _reported_concepts(r["payload"])
                    if d.get("concept") in _IS_REVENUE), None)
        if rev is not None and r.get("year") is not None and r.get("quarter") is not None:
            revenues[(r["year"], r["quarter"])] = rev
    ordered = [revenues[k] for k in sorted(revenues)]
    if len(ordered) >= 4:
        growths = [b / a - 1.0 for a,
                   b in zip(ordered, ordered[1:]) if a and b]
        if growths:
            pos = sum(1 for g in growths if g > 0)
            components.append(Component("moat", "growth_consistency",
                                        pos / len(growths) * 100.0, 0.20, "live"))
        else:
            components.append(
                Component("moat", "growth_consistency", 50.0, 0.20, "neutral"))
    else:
        components.append(
            Component("moat", "growth_consistency", 50.0, 0.20, "neutral"))

    # 4. scale advantage (15%) — market cap vs peer median when peers present
    profile = _fetch_one(con, "raw_company_profile", "ticker = ?", [ticker])
    cap_m = _num(profile["payload"].get(
        "marketCapitalization")) if profile else None
    cap = cap_m * 1e6 if cap_m is not None else None  # Finnhub caps arrive in $M
    if cap is None:
        components.append(
            Component("moat", "scale_advantage", 50.0, 0.15, "neutral"))
        return components
    peers = _fetch_one(con, "raw_peers", "ticker = ?", [ticker])
    peer_caps: list[float] = []
    if peers:
        for p in (peers["payload"].get("peers") or []):
            p_row = _fetch_one(con, "raw_company_profile", "ticker = ?", [p])
            pc_m = _num(p_row["payload"].get(
                "marketCapitalization")) if p_row else None
            if pc_m is not None:
                peer_caps.append(pc_m * 1e6)
    if peer_caps:
        ratio = cap / statistics.median(peer_caps) if peer_caps else 1.0
        score = _clamp(40.0 + math.log10(max(ratio, 1e-6)) * 30.0, 10.0, 95.0)
        components.append(
            Component("moat", "scale_advantage", score, 0.15, "live"))
    else:
        scale = 90.0 if cap >= 1e11 else 75.0 if cap >= 1e10 else 60.0 if cap >= 1e9 else 40.0
        components.append(
            Component("moat", "scale_advantage", scale, 0.15, "proxy"))
    return components


# ---------------------------------------------------------------------------
# Volatility (separate score, higher = riskier)
# ---------------------------------------------------------------------------

def _volatility_components(con: Any, ticker: str, price: float | None) -> list[Component]:
    components: list[Component] = []
    basic = _basic_rows(con, ticker)

    # 1. realized vol (30%) — annualized sigma of daily returns, last ~252 bars
    rets = [r[0] for r in con.execute(
        """
        SELECT return_1d FROM staging.stg_prices_daily
        WHERE ticker = ? AND return_1d IS NOT NULL
        ORDER BY date DESC LIMIT 252
        """,
        [ticker],
    ).fetchall()]
    ann = None
    if len(rets) >= 20:
        ann = statistics.pstdev(rets) * math.sqrt(252)
    score = (_clamp(ann * 2.5 * 100.0, 2.0, 100.0)
             if ann is not None else None)
    components.append(Component("volatility", "realized_vol",
                                score if score is not None else 50.0, 0.30,
                                "live" if score is not None else "neutral"))

    # 2. ATR% (30%)
    ind = con.execute(
        "SELECT atr_14 FROM mart.m_technical_indicators WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    atr = ind[0] if ind else None
    if atr and price:
        score = _clamp(atr / price * 100.0 * 25.0, 2.0, 100.0)
        components.append(
            Component("volatility", "atr_pct", score, 0.30, "live"))
    else:
        components.append(
            Component("volatility", "atr_pct", 50.0, 0.30, "neutral"))

    # 3. BBANDS bandwidth percentile vs own 1yr history (25%)
    bws: list[float] = []
    for r in con.execute(
        """
        SELECT bb_lower_20, bb_mid_20, bb_upper_20
        FROM mart.m_technical_indicators
        WHERE ticker = ? AND bb_mid_20 IS NOT NULL
        ORDER BY date DESC LIMIT 252
        """,
        [ticker],
    ).fetchall():
        lo, mid, hi = r
        if lo and mid and hi:
            bws.append((hi - lo) / mid)
    score = None
    if len(bws) >= 20:
        pct = _percentile_of(bws[0], bws[1:])
        if pct is not None:
            score = _clamp(pct * 0.9 + 5.0, 5.0, 95.0)
    components.append(Component("volatility", "bb_bandwidth_percentile",
                                score if score is not None else 50.0, 0.25,
                                "live" if score is not None else "neutral"))

    # 4. beta (15%)
    beta = _latest_series(basic, "beta")
    if beta is None:
        profile = _fetch_one(con, "raw_company_profile",
                             "ticker = ?", [ticker])
        beta = _num((profile or {}).get("beta")) if profile else None
    components.append(Component("volatility", "beta",
                                _clamp(30.0 + ((beta or 1.0) - 1.0)
                                       * 50.0, 0.0, 100.0), 0.15,
                                "live" if beta is not None else "proxy"))
    return components


# ---------------------------------------------------------------------------
# Fair value (DCF + own-history comparables, per MODEL.md)
# ---------------------------------------------------------------------------

def _reported_concepts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten /stock/financials-reported rows: live payloads nest XBRL
    concepts under report.{bs,ic,cf}; legacy payloads carry a flat `data`
    list. Concept names are stripped of their taxonomy prefix (us-gaap_...)."""
    flat = payload.get("data")
    if flat is None:
        flat = [d for section in payload.get("report", {}).values() for d in section]
    out: list[dict[str, Any]] = []
    for d in flat or []:
        row = dict(d)
        concept = str(row.get("concept") or "")
        for prefix in ("us-gaap_", "ifrs-full_", "srt_", "dei_", "us-gaap_2_"):
            if concept.startswith(prefix):
                concept = concept[len(prefix):]
                break
        row["concept"] = concept
        out.append(row)
    return out


def _reported_ttm(reported: list[dict[str, Any]], concepts: tuple[str, ...]) -> float | None:
    """Trailing-twelve-months total of an income/cash-flow XBRL concept over
    the last 4 filings. A missing concept in ANY of the last 4 filings
    aborts the TTM (defensive, no silent partial sums)."""
    vals: list[float] = []
    for r in reported[-4:]:
        v = next((_num(d.get("value")) for d in _reported_concepts(r["payload"])
                  if d.get("concept") in concepts), None)
        if v is None:
            return None
        vals.append(v)
    return sum(vals)


def _reported_latest(reported: list[dict[str, Any]], concepts: tuple[str, ...]) -> float | None:
    """Latest snapshot of a balance-sheet XBRL concept (no summing)."""
    for r in reversed(reported[-4:]):
        v = next((_num(d.get("value")) for d in _reported_concepts(r["payload"])
                  if d.get("concept") in concepts), None)
        if v is not None:
            return v
    return None


def _fair_value(con: Any, ticker: str, price: float, basic: list[dict[str, Any]],
                profile: dict[str, Any] | None) -> tuple[float | None, list[str]]:
    """Blended DCF + history-multiple fair value; returns (value, provenance)."""
    if price <= 0:
        return None, []
    sources: list[str] = []
    surprise_rows = _eps_surprise_rows(con, ticker)
    trailing = _trailing_eps(surprise_rows)
    fwd = _forward_eps(con, ticker)
    if trailing and trailing > 0 and fwd:
        g_fwd = _clamp(fwd / (trailing * 4.0) - 1.0, *FAIR_VALUE["growth_clamp"])
        sources.append("growth=earnings_estimate")
    else:
        # free-tier forward estimates aren't available: fall back to trailing
        # EPS growth annualized from /stock/earnings actuals (which we hold)
        actuals = [_num(r["payload"].get("actual")) for r in surprise_rows]
        actuals = [a for a in actuals if a is not None and a > 0]
        if len(actuals) >= 4:
            ann = (actuals[-1] / actuals[0]) ** (4.0 / (len(actuals) - 1)) - 1.0
            g_fwd = _clamp(ann, *FAIR_VALUE["growth_clamp"])
            sources.append("growth=trailing_eps")
        else:
            g_fwd = _clamp(_latest_series(basic, "gGrowth") or 0.0,
                           *FAIR_VALUE["growth_clamp"])
            sources.append("growth=proxy")
    beta = _latest_series(basic, "beta") or 1.0
    r = FAIR_VALUE["risk_free_rate"] + beta * FAIR_VALUE["equity_risk_premium"]

    # ---- DCF leg: TTM owner FCF, 5y stage-1 growth, TV ----
    reported = _reported_rows(con, ticker)
    shares = (_num(profile["payload"].get(
        "shareOutstanding")) * 1e6) if profile else None
    dcf_ps: float | None = None
    ocf = _reported_ttm(reported, _CF_OCF)
    capex = _reported_ttm(reported, _CF_CAPEX)
    owner_fcf = (
        ocf - capex) if (ocf is not None and capex is not None) else None
    if owner_fcf and owner_fcf > 0:
        # balance-sheet items are snapshots, not flows
        liabilities = _reported_latest(reported, _BS_LIABILITIES)
        cash = _reported_latest(reported, _BS_CASH)
        if shares and shares > 0 and liabilities is not None and cash is not None:
            g = _clamp(g_fwd, 0.0, FAIR_VALUE["growth_cap"])
            years = FAIR_VALUE["forecast_years"]
            fcf_series = [owner_fcf *
                          (1 + g) ** t for t in range(1, years + 1)]
            pv = sum(f / (1 + r) ** t for t,
                     f in enumerate(fcf_series, start=1))
            tv = fcf_series[-1] * (1 + FAIR_VALUE["terminal_growth"]) / max(
                r - FAIR_VALUE["terminal_growth"], 1e-6)
            equity = pv + tv / (1 + r) ** years - (liabilities - cash)
            if equity > 0:
                dcf_ps = equity / shares
                sources.append("dcf")

    # ---- Comparables leg: own historical median multiples ----
    comps: list[float] = []
    pes = _eps_pe_history(price, surprise_rows)
    if len(pes) >= 8 and fwd and fwd > 0:
        comps.append(statistics.median(pes) * fwd)
    ps_hist = _ps_history(price, basic)
    rps = _latest_series(basic, "salesPerShareTTM")
    if len(ps_hist) >= 8 and rps and rps > 0:
        comps.append(statistics.median(ps_hist) * rps * (1 + g_fwd))
    ev_ebitda = _latest_series(basic, "evToEBITDA")
    ebitd_ps = _latest_series(basic, "ebitdPerShareTTM")
    ebitda_ttm = (ebitd_ps * shares) if (ebitd_ps and ebitd_ps > 0 and shares and shares > 0) else None
    if ev_ebitda and ebitda_ttm and ebitda_ttm > 0 and shares and shares > 0:
        comps.append(ev_ebitda * (ebitda_ttm * (1 + g_fwd)) / shares)
    comps_ps = _mean(comps) if comps else None
    if comps:
        sources.append("comps")

    if dcf_ps is None and comps_ps is None:
        return None, []
    fair = (FAIR_VALUE["dcf_weight"] * (dcf_ps or comps_ps)
            + (1.0 - FAIR_VALUE["dcf_weight"]) * (comps_ps or dcf_ps))

    # ---- sanity clamps: within [0.5x, 2x] of price, widened by 52w range ----
    lo_52 = _latest_series(basic, "52WeekLow") or price
    hi_52 = _latest_series(basic, "52WeekHigh") or (price * 2.0)
    lo = min(price * FAIR_VALUE["clamp_floor_scale"], lo_52)
    hi = max(price * FAIR_VALUE["clamp_multiplier"], hi_52)
    return _clamp(fair, lo, hi), sources


# ---------------------------------------------------------------------------
# Composition + persistence
# ---------------------------------------------------------------------------

def _rating_for(score: float) -> str:
    for min_score, rating in RATING_BANDS:
        if score >= min_score:
            return rating
    return FALLBACK_RATING


def _holding_style(volatility_score: float) -> str:
    for style, upper in VOLATILITY_BANDS:
        if upper is None or volatility_score < upper:
            return style
    return "day trade"


def _buy_plan(con: Any, ticker: str, rating: str, fair_value: float | None,
              volatility_score: float, price: float | None) -> dict[str, Any] | None:
    if rating not in ("Buy", "Strong Buy") or fair_value is None or price is None:
        return None
    buy_price = min(price, fair_value * (1.0 - BUY_PLAN["margin_of_safety"]))
    style = _holding_style(volatility_score)
    row = con.execute(
        "SELECT atr_14 FROM mart.m_technical_indicators WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    atr = row[0] if row else None
    k = BUY_PLAN["atr_multiplier"][style]
    stop = (buy_price - k * atr) if atr else buy_price * 0.85
    stop = max(stop, buy_price * BUY_PLAN["stop_floor_scale"])
    return {"price": buy_price, "stop_loss": stop, "holding_style": style}


def score_ticker(warehouse: Warehouse, ticker: str, *, now: datetime | None = None) -> ScoreResult:
    """Compute + persist the full score set for one ticker (snapshot tables)."""
    now = now or datetime.now(timezone.utc)
    with warehouse.connect() as con:
        profile = _fetch_one(con, "raw_company_profile",
                             "ticker = ?", [ticker])
        basic = _basic_rows(con, ticker)
        surprise_rows = _eps_surprise_rows(con, ticker)
        trailing = _trailing_eps(surprise_rows)

        price: float | None = None
        q = _fetch_one(con, "raw_quotes", "ticker = ?", [ticker])
        if q:
            price = _num(q["payload"].get("c"))
        if price is None:
            row = con.execute(
                "SELECT close FROM staging.stg_prices_daily WHERE ticker = ? ORDER BY date DESC LIMIT 1",
                [ticker],
            ).fetchone()
            price = row[0] if row else None

        g_fwd = _eps_growth(con, ticker, surprise_rows)
        fair_value, fair_sources = _fair_value(
            con, ticker, price, basic, profile) if price else (None, [])

        valuation = _category_score("valuation", VALUATION_SUB_WEIGHTS,
                                    _valuation_components(con, ticker, surprise_rows, price, fair_value))
        trend = _category_score(
            "trend", TREND_SUB_WEIGHTS, _trend_components(con, ticker, price))
        sentiment = _category_score(
            "sentiment", SENTIMENT_SUB_WEIGHTS, _news_components(con, ticker))
        moat = _category_score("moat", MOAT_SUB_WEIGHTS,
                               _moat_components(con, ticker))
        vol_components = _volatility_components(con, ticker, price)
        volatility = _category_score(
            "volatility", VOLATILITY_SUB_WEIGHTS, vol_components)

        confidence = sum(CONFIDENCE_WEIGHTS[c.name] * c.score
                         for c in (valuation, trend, sentiment, moat))
        rating = _rating_for(confidence)
        override = (valuation.score < VALUATION_OVERRIDE["below"]
                    or valuation.score > VALUATION_OVERRIDE["above"])
        if override:
            capped = valuation.score < VALUATION_OVERRIDE["below"]
            if capped and rating not in ("Sell", "Strong Sell"):
                rating = VALUATION_OVERRIDE["rating"]
            if not capped and rating in ("Sell", "Strong Sell"):
                rating = VALUATION_OVERRIDE["rating"]

        target = None
        if fair_value is not None:
            g = _clamp(g_fwd if g_fwd is not None else 0.0,
                       *FAIR_VALUE["growth_clamp"])
            target = fair_value * (1.0 + g)
        buy_plan = _buy_plan(con, ticker, rating,
                             fair_value, volatility.score, price)

        result = ScoreResult(
            ticker=ticker,
            computed_at=now,
            confidence_score=confidence,
            rating=rating,
            categories=[valuation, trend, sentiment, moat],
            volatility_score=volatility.score,
            volatility_components=vol_components,
            fair_value=fair_value,
            target_price=target,
            fair_value_sources=fair_sources,
            valuation_override_applied=override,
            buy_plan=buy_plan,
        )
        _persist(con, result, valuation, volatility)
    return result


def _persist(con: Any, result: ScoreResult, valuation: CategoryScore,
             volatility: CategoryScore) -> None:
    """Upsert the three snapshot tables (one row per ticker, latest run wins)."""
    v = result
    by_name = {c.name: c.score for c in v.categories}
    con.execute(
        """
        INSERT INTO mart.m_confidence_ratings
            (ticker, computed_at, confidence_score, rating, valuation_score,
             trend_score, sentiment_score, moat_score, volatility_score,
             fair_value, target_price, valuation_override_applied)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (ticker) DO UPDATE SET
            computed_at = excluded.computed_at,
            confidence_score = excluded.confidence_score,
            rating = excluded.rating,
            valuation_score = excluded.valuation_score,
            trend_score = excluded.trend_score,
            sentiment_score = excluded.sentiment_score,
            moat_score = excluded.moat_score,
            volatility_score = excluded.volatility_score,
            fair_value = excluded.fair_value,
            target_price = excluded.target_price,
            valuation_override_applied = excluded.valuation_override_applied
        """,
        [v.ticker, v.computed_at, v.confidence_score, v.rating,
         valuation.score, by_name["trend"], by_name["sentiment"], by_name["moat"],
         v.volatility_score, v.fair_value, v.target_price,
         v.valuation_override_applied],
    )
    bp = v.buy_plan or {}
    con.execute(
        """
        INSERT INTO mart.m_buy_plans
            (ticker, computed_at, advised_buy_price, stop_loss, holding_style)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (ticker) DO UPDATE SET
            computed_at = excluded.computed_at,
            advised_buy_price = excluded.advised_buy_price,
            stop_loss = excluded.stop_loss,
            holding_style = excluded.holding_style
        """,
        [v.ticker, v.computed_at, bp.get("price"), bp.get("stop_loss"),
         bp.get("holding_style")],
    )

    con.execute(
        'DELETE FROM mart.m_rating_components WHERE ticker = ?', [v.ticker])
    for cat in (*v.categories, volatility):
        for comp in cat.components:
            con.execute(
                """
                INSERT INTO mart.m_rating_components
                    (ticker, computed_at, category, component, value, weight, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [v.ticker, v.computed_at, comp.category, comp.name, comp.value,
                 comp.weight, comp.source],
            )
