"""Tests for the backtest harness and point-in-time scoring.

Core guarantees under test:
- as_of scoring cannot see future bars (no lookahead)
- persist=False leaves the mart snapshot tables untouched
- forward returns are computed from the exact bars bracketing each as_of
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from stockidence.backtest import BacktestRow, render, run_backtest, summarize
from stockidence.mart.mart import rebuild_prices_daily, rebuild_technical_indicators
from stockidence.mart.scoring import score_ticker
from stockidence.storage import Warehouse

DAY0 = date(2025, 1, 1)


def _seed_path(warehouse: Warehouse, ticker: str, closes: list[float]) -> None:
    """Land a custom close path and rebuild the staging/mart layers."""
    bars = []
    for i, c in enumerate(closes):
        bars.append({
            "ticker": ticker,
            "date": DAY0 + timedelta(days=i),
            "open": str(c * 0.99), "high": str(c * 1.01),
            "low": str(c * 0.98), "close": str(c), "volume": "100",
        })
    warehouse.land("raw_prices_daily", bars)
    rebuild_prices_daily(warehouse, ticker)
    rebuild_technical_indicators(warehouse, ticker)


@pytest.fixture
def wh(tmp_path):
    w = Warehouse(tmp_path / "bt.duckdb")
    w.init_schema()
    return w


def _snapshot_rows(wh: Warehouse, sql: str, args: list) -> int:
    return wh.connect(read_only=True).execute(sql, args).fetchone()[0]


def _realized_vol(result) -> float:
    return next(x.value for x in result.volatility_components
                if x.name == "realized_vol")


def test_as_of_scoring_has_no_lookahead(wh):
    # 200-bar calm uptrend into a 60-day crash; a point-in-time replay at
    # the peak must not feel the crash.
    closes = [40.0 + i * 0.5 for i in range(200)]           # 40 -> 139.5
    closes += [139.5 * (0.985 ** k) for k in range(1, 61)]  # crash to ~62
    _seed_path(wh, "CRSH", closes)

    peak = DAY0 + timedelta(days=199)
    past = score_ticker(wh, "CRSH", as_of=peak, persist=False)
    live = score_ticker(wh, "CRSH", persist=False)  # falls back to last bar

    assert _realized_vol(past) < _realized_vol(live)  # crash inflates vol
    assert past.volatility_score < live.volatility_score


def test_persist_flag_controls_snapshot_writes(wh):
    closes = [40.0 + i for i in range(230)]
    _seed_path(wh, "PERS", closes)
    as_of = DAY0 + timedelta(days=229)

    score_ticker(wh, "PERS", as_of=as_of, persist=False)
    n = _snapshot_rows(
        wh, "SELECT COUNT(*) FROM mart.m_confidence_ratings WHERE ticker = ?",
        ["PERS"])
    assert n == 0

    score_ticker(wh, "PERS", persist=True)
    n = _snapshot_rows(
        wh, "SELECT COUNT(*) FROM mart.m_confidence_ratings WHERE ticker = ?",
        ["PERS"])
    assert n == 1


def test_run_backtest_forward_return_math(wh):
    closes = [40.0 + i for i in range(40)]  # deterministic +1.0/bar ramp
    _seed_path(wh, "RAMP", closes)

    rows = run_backtest(wh, ["RAMP"], min_bars=10,
                        horizons=(5,), step_days=7)
    assert rows, "expected eligible replay dates"

    for row in rows:
        i = (row.as_of - DAY0).days
        expected = (40.0 + i + 5) / (40.0 + i) - 1.0
        assert row.fwd_returns[5] == pytest.approx(expected)


def test_run_backtest_skips_thin_history(wh):
    _seed_path(wh, "THIN", [50.0] * 20)  # below any sane min_bars
    rows = run_backtest(wh, ["THIN"], min_bars=30, horizons=(5,))
    assert rows == []


def test_summarize_directional_semantics():
    def _row(rating: str, ret: float) -> BacktestRow:
        return BacktestRow(ticker="X", as_of=DAY0, rating=rating,
                           confidence=60.0, volatility=40.0,
                           category_scores={}, fwd_returns={5: ret}, fwd_vols={5: 0.01})

    rows = [
        *(_row("Buy", r) for r in (0.05, 0.10, -0.02)),   # 2/3 up
        *(_row("Sell", r) for r in (-0.05, -0.08, 0.03)),  # 2/3 down
        *(_row("Hold", r) for r in (0.50, -0.50)),         # direction-agnostic
    ]
    summaries = {(s.rating, s.horizon): s for s in summarize(rows, (5,))}
    buy = summaries[("Buy", 5)]
    sell = summaries[("Sell", 5)]
    hold = summaries[("Hold", 5)]
    assert buy.directional_accuracy == pytest.approx(2 / 3)
    assert sell.directional_accuracy == pytest.approx(2 / 3)
    assert hold.mean_return == pytest.approx(0.0)


def test_render_smoke():
    def _row(rating: str, ret: float) -> BacktestRow:
        return BacktestRow(ticker="X", as_of=DAY0, rating=rating,
                           confidence=60.0, volatility=40.0,
                           category_scores={}, fwd_returns={20: ret}, fwd_vols={20: 0.02})

    text = render([_row("Buy", 0.04), _row("Strong Buy", 0.09)], (20,))
    assert "replays=2" in text
    assert "acc 20d" in text
    assert render([], (20,)).startswith("replays=0")
