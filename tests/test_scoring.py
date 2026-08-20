"""End-to-end tests for the scoring layer (mart/scoring.py).

A fully-seeded "cheap, trending up, liked" ticker should produce a Buy/Strong
Buy with a buy plan; a bar-only ticker should degrade to all-neutral 50s.
Validity of component math is spot-checked against hand-computable values."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from stockidence.mart.mart import rebuild_prices_daily, rebuild_technical_indicators
from stockidence.mart.scoring import score_ticker
from stockidence.storage import Warehouse

NOW = datetime.now(timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    return wh


def _seed_bars(warehouse: Warehouse, ticker: str, n: int = 280, start: float = 40.0) -> None:
    # steady ramp with a small gap-free band: closes 41..320, spread {v-1, v+1}
    bars = []
    day0 = date(2026, 6, 1)
    for i in range(n):
        v = start + i * 1.0
        bars.append({
            "ticker": ticker,
            "date": day0 + timedelta(days=i),
            "open": str(v - 0.5), "high": str(v + 1), "low": str(v - 1),
            "close": str(v + 0.5), "volume": "100",
        })
    warehouse.land("raw_prices_daily", bars)
    rebuild_prices_daily(warehouse, ticker)
    rebuild_technical_indicators(warehouse, ticker)


def _seed_quotes(warehouse: Warehouse, ticker: str, price: float) -> None:
    warehouse.land("raw_quotes",
                   [{"ticker": ticker, "c": price, "h": price + 1, "l": price - 1,
                     "o": price, "pc": price - 0.5, "t": NOW_MS}])


def _seed_profile(warehouse: Warehouse, ticker: str, *, cap_m: float = 150_000.0,
                  shares_m: float = 1000.0) -> None:
    warehouse.land("raw_company_profile",
                   [{"ticker": ticker, "name": "Test Corp", "marketCapitalization": cap_m,
                     "shareOutstanding": shares_m, "currency": "USD", "exchange": "NASDAQ"}])


def _quarter(year: int, quarter: int) -> tuple[int, int]:
    return year, quarter


def _seed_fundamentals(warehouse: Warehouse, ticker: str) -> None:
    """8 quarters of rising EPS (+5% surprises), fwd estimate, metrics, filings.

    Note: raw_basic_financials rows are keyed (ticker, quarter, year, metric);
    the metric column was added so periods hold every metric without PK
    collisions (metrics used to clobber each other at the same period)."""
    now_ay = NOW.year
    surprises, basics, reported = [], [], []
    for k in range(8):  # EPS history: (now-1, Q1..Q4) + (now, Q1..Q4)
        y, q = _quarter(now_ay - 1 + k // 4, k % 4 + 1)
        eps = 2.0 + k * 0.05
        surprises.append({"ticker": ticker, "quarter": q, "year": y,
                          "symbol": ticker,
                          "actual": eps, "estimate": eps - 0.1,
                          "surprise": 0.1, "surprisePercent": 5.0})
    for k in range(4):  # salesPerShareTTM: (now-1, Q1..Q4) — latest is 13.1
        y, q = now_ay - 1, k + 1
        basics.append({"ticker": ticker, "quarter": q, "year": y,
                       "metric": "salesPerShareTTM", "period": f"{y}-Q{q}",
                       "v": 12.5 + k * 0.2, "freq": "quarterly"})
    basics.extend([
        # keys are (ticker, quarter, year, metric) since the metric-column
        # fix — distinct keys per metric are harmless but keep rows readable
        {"ticker": ticker, "quarter": 4, "year": now_ay - 2, "metric": "netMargin",
         "period": f"{now_ay - 2}-Q4", "v": 0.60, "freq": "annual"},
        {"ticker": ticker, "quarter": 1, "year": now_ay, "metric": "returnOnEquityTTM",
         "period": f"{now_ay}-Q1", "v": 0.25, "freq": "quarterly"},
        {"ticker": ticker, "quarter": 2, "year": now_ay, "metric": "beta",
         "period": f"{now_ay}-Q2", "v": 1.0, "freq": "quarterly"},
        {"ticker": ticker, "quarter": 3, "year": now_ay, "metric": "52WeekHigh",
         "period": f"{now_ay}-Q3", "v": 150.0, "freq": "quarterly"},
        {"ticker": ticker, "quarter": 4, "year": now_ay, "metric": "52WeekLow",
         "period": f"{now_ay}-Q4", "v": 60.0, "freq": "quarterly"},
        {"ticker": ticker, "quarter": 2, "year": now_ay - 2, "metric": "gGrowth",
         "period": str(now_ay - 2), "v": 0.10, "freq": "annual"},
        {"ticker": ticker, "quarter": 3, "year": now_ay - 2, "metric": "ebitdaTTM",
         "period": str(now_ay - 2), "v": 8_000_000_000.0, "freq": "annual"},
        {"ticker": ticker, "quarter": 1, "year": now_ay - 2, "metric": "evToEBITDA",
         "period": str(now_ay - 2), "v": 14.0, "freq": "annual"},
    ])
    for k in range(4):
        y, q = _quarter(now_ay - 1 + (k + 1) // 4, (k + 1) % 4 or 4)
        reported.append({
            "ticker": ticker, "quarter": q, "year": y,
            "data": [
                {"label": "Operating Cash Flow", "concept": "OperatingCashFlow",
                 "unit": "USD", "value": "5000000000"},
                {"label": "CapEx", "concept": "PaymentsToAcquirePropertyPlantAndEquipment",
                 "unit": "USD", "value": "700000000"},
                {"label": "Liabilities", "concept": "TotalLiabilities",
                 "unit": "USD", "value": "60000000000"},
                {"label": "Cash", "concept": "CashAndCashEquivalentsAtCarryingValue",
                 "unit": "USD", "value": "20000000000"},
                {"label": "Revenues", "concept": "Revenues",
                 "unit": "USD", "value": f"{4_000_000_000 * (k + 1)}"},
                {"label": "Net Income", "concept": "NetIncomeLoss",
                 "unit": "USD", "value": f"{500_000_000 * (k + 1)}"},
                {"label": "Equity", "concept": "StockholdersEquity",
                 "unit": "USD", "value": "25000000000"},
            ],
        })
    warehouse.land("raw_eps_surprises", surprises)
    warehouse.land("raw_basic_financials", basics)
    warehouse.land("raw_financials_reported", reported)
    warehouse.land("raw_earnings_calendar", [
        {"symbol": ticker, "quarter": ((NOW.month + 2) % 4), "year": NOW.year,
         "epsEstimate": 2.6,
         "reportDate": (NOW + timedelta(days=30)).date().isoformat(),
         "fiscalDateEnding": (NOW + timedelta(days=120)).date().isoformat()},
    ])


def _seed_sentiment(warehouse: Warehouse, ticker: str) -> None:
    now_d = NOW.date()
    warehouse.land("raw_news_articles", [
        {"article_id": f"{ticker}-n{i}", "datetime": NOW_MS - i * 86_400_000,
         "headline": f"article {i}", "summary": f"summary {i}", "url": f"https://x/{ticker}/{i}"}
        for i in range(4)
    ])
    warehouse.land("news_ticker_sentiment", [
        {"article_id": f"{ticker}-n{i}", "ticker": ticker,
         "ticker_sentiment_score": 0.5, "relevance_score": 0.8}
        for i in range(4)
    ])
    warehouse.land("raw_recommendation_trends", [
        {"ticker": ticker, "period": now_d,
         "strongBuy": 3, "buy": 2, "hold": 1, "sell": 0, "strongSell": 0,
         "targetMeanPrice": 130.0},
        {"ticker": ticker, "period": now_d - timedelta(days=7),
         "strongBuy": 2, "buy": 2, "hold": 2, "sell": 0, "strongSell": 0,
         "targetMeanPrice": 120.0},
    ])
    warehouse.land("raw_insider_sentiment", [
        {"ticker": ticker, "year": now_d.year, "month": max(1, now_d.month - 1), "change": 1000.0, "mspr": 0.3},
        {"ticker": ticker, "year": now_d.year, "month": now_d.month, "change": 500.0, "mspr": 0.5},
    ])
    warehouse.land("raw_transcript_segments", [
        {"ticker": ticker, "quarter": 4, "year": now_d.year - 1, "speaker_sequence": 0,
         "speaker": "CEO", "speaker_title": "Chief Executive Officer",
         "content": "We delivered strong growth and our guidance remains confident."},
        {"ticker": ticker, "quarter": 4, "year": now_d.year - 1, "speaker_sequence": 1,
         "speaker": "CFO", "speaker_title": "Chief Financial Officer",
         "content": "Margins are under pressure from weaker demand."},
    ])


@pytest.fixture
def rich_warehouse(warehouse):
    _seed_bars(warehouse, "UND1")
    _seed_quotes(warehouse, "UND1", price=319.5)  # last bar close of the ramp
    _seed_profile(warehouse, "UND1")
    _seed_fundamentals(warehouse, "UND1")
    _seed_sentiment(warehouse, "UND1")
    return warehouse


def test_rich_ticker_scores_buy_with_plan(rich_warehouse):
    result = score_ticker(rich_warehouse, "UND1")
    by = {c.name: c for c in result.categories}

    assert 55.0 <= result.confidence_score <= 85.0
    assert result.rating == "Buy"
    assert 50.0 <= by["valuation"].score <= 80.0
    assert by["trend"].score > 60.0
    assert result.volatility_score > 0.0

    assert 300.0 <= result.fair_value <= 400.0  # DCF+comps blend, sane vs 2x clamp
    assert "dcf" in result.fair_value_sources
    growth = 2.6 / 2.275 - 1.0  # fwd eps 2.6*4 vs trailing mean 2.275*4
    assert result.target_price / result.fair_value == pytest.approx(1.0 + growth, rel=1e-2)

    assert result.buy_plan is not None
    assert result.buy_plan["price"] == pytest.approx(
        min(319.5, result.fair_value * (1 - 0.15)))
    assert result.buy_plan["holding_style"] in ("long-term hold", "swing trade", "day trade")
    assert 0.0 < result.buy_plan["stop_loss"] < 319.5


def test_scoring_persists_snapshot_tables(rich_warehouse):
    score_ticker(rich_warehouse, "UND1")
    con = rich_warehouse.connect(read_only=True)
    row = con.execute(
        "SELECT ticker, rating, confidence_score, fair_value FROM mart.m_confidence_ratings"
    ).fetchone()
    assert row[0] == "UND1" and row[1] == "Buy"
    assert row[2] > 50.0 and 300.0 <= row[3] <= 400.0

    comps = con.execute(
        "SELECT category, component, source FROM mart.m_rating_components ORDER BY category, component"
    ).fetchall()
    categories = {c[0] for c in comps}
    assert categories == {"valuation", "trend", "sentiment", "moat", "volatility"}
    sources = {c[2] for c in comps}
    assert "live" in sources  # rich fixture → almost everything is live

    bp = con.execute(
        "SELECT advised_buy_price, stop_loss, holding_style FROM mart.m_buy_plans"
    ).fetchone()
    fair = con.execute(
        "SELECT fair_value FROM mart.m_confidence_ratings WHERE ticker = 'UND1'"
    ).fetchone()[0]
    assert bp[0] == pytest.approx(min(319.5, fair * (1 - 0.15))) and bp[1] > 0.0


def test_scoring_rerun_is_idempotent(rich_warehouse):
    score_ticker(rich_warehouse, "UND1")
    first = rich_warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM mart.m_rating_components"
    ).fetchone()[0]
    score_ticker(rich_warehouse, "UND1")
    second = rich_warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM mart.m_rating_components"
    ).fetchone()[0]
    assert first == second
    assert rich_warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM mart.m_confidence_ratings"
    ).fetchone()[0] == 1


def test_bar_only_ticker_degrades_to_neutral(warehouse):
    # Bars exist (so trend/volatility are live), but no fundamentals or
    # sentiment: valuation/moat/sentiment collapse to neutral 50s, and the
    # weighted confidence lands in Hold territory without an override.
    _seed_bars(warehouse, "BARE")
    _seed_quotes(warehouse, "BARE", price=319.5)
    result = score_ticker(warehouse, "BARE")

    assert result.fair_value is None
    assert result.target_price is None
    assert result.buy_plan is None
    assert result.valuation_override_applied is False
    assert result.rating == "Hold"
    assert 45.0 <= result.confidence_score <= 55.0
    by = {c.name: c for c in result.categories}
    assert by["valuation"].score == pytest.approx(50.0)
    assert by["sentiment"].score == pytest.approx(50.0)
    assert by["moat"].score == pytest.approx(50.0)
    assert all(c.source == "neutral" for c in by["valuation"].components)

    comps = warehouse.connect(read_only=True).execute(
        "SELECT category, COUNT(*) FROM mart.m_rating_components GROUP BY category"
    ).fetchall()
    assert dict(comps)["valuation"] == 6  # every sub-score persisted, neutral