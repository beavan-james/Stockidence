"""Tests for the staging derivations: resampling, indicator math, analytics.

Fixtures use hand-constructible bar series (constant-gap bars, monotonic
trends) so expected values are derivable by pen and paper — the tests assert
exact numbers for the pure functions and structural/sanity checks for the
warehouse rebuilds."""

from __future__ import annotations

from datetime import date

import pytest

from stockidence.mart.mart import (
    adx,
    atr,
    cci,
    directional_indexes,
    ema,
    rebuild_advanced_analytics,
    rebuild_prices_monthly,
    rebuild_prices_weekly,
    rebuild_technical_indicators,
    rsi,
    sma,
    stoch,
)
from stockidence.staging.staging import rebuild_prices_daily
from stockidence.storage import Warehouse

W1 = date(2026, 6, 1)  # Monday
W2 = date(2026, 6, 8)  # Monday


def _seed_bars(warehouse: Warehouse, ticker: str, bars: list[dict]) -> None:
    warehouse.land("raw_prices_daily", bars, fetched_at=None)
    rebuild_prices_daily(warehouse, ticker)


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    return wh


# ---------------------------------------------------------------- pure math

def test_ema_textbook_values():
    assert ema([1, 2, 3, 4, 5], span=3) == pytest.approx([1.0, 1.5, 2.25, 3.125, 4.0625])


def test_sma_values():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_rsi_all_up_is_100():
    closes = [100.0 + i for i in range(20)]
    r = rsi(closes)
    assert r[-1] == pytest.approx(100.0)


def test_rsi_all_down_is_0():
    closes = [200.0 - i for i in range(20)]
    r = rsi(closes)
    assert r[-1] == pytest.approx(0.0)
    assert all(v is None for v in r[:15])


def test_atr_constant_spread():
    # flat bars within [0,1], close mid-range: TRUE range = high - low = 1 every day
    highs = [1.0] * 30
    lows = [0.0] * 30
    closes = [0.5] * 30
    a = atr(highs, lows, closes)
    assert a[-1] == pytest.approx(1.0)
    assert a[0] is None  # no prior bar to form a true range at index 0


def test_adx_range_and_shapes():
    # tame monotonic uptrend: ADX should emerge positive and bounded by 100
    n = 60
    highs = [100.0 + i * 0.5 for i in range(n)]
    lows = [99.0 + i * 0.5 for i in range(n)]
    closes = [99.5 + i * 0.5 for i in range(n)]
    d = adx(highs, lows, closes)
    assert d[0] is None and d[26] is None
    assert d[27] is not None  # first ADX at bar 2*period - 1
    assert d[-1] is not None
    assert 0.0 <= d[-1] <= 100.0
    assert len(d) == n


def test_cci_constant_bars_is_zero():
    n = 30
    highs = [10.0] * n
    lows = [9.0] * n
    closes = [9.5] * n
    c = cci(highs, lows, closes)
    assert all(v == 0.0 for v in c[19:])


def test_directional_indexes_pure_uptrend():
    # +DM-only ramp: +DI = 100 * (+DM / ATR), -DI = 0 once Wilder seeds (bar 14).
    # TR = |high - prev close| = 1.5 here, +DM = 1  →  +DI = 66.67
    n = 40
    highs = [100.0 + i for i in range(n)]
    lows = [99.0 + i for i in range(n)]
    closes = [99.5 + i for i in range(n)]
    plus, minus = directional_indexes(highs, lows, closes)
    assert plus[13] is None and minus[13] is None
    assert plus[14:] == pytest.approx([2.0 / 3.0 * 100.0] * (n - 14))
    assert minus[14:] == pytest.approx([0.0] * (n - 14))


def test_stoch_rising_ramp_hits_100():
    # Close pinned at the top of every 14-bar window: %K = 100, %D lags 3
    n = 40
    highs = [10.0 + i * 0.1 for i in range(n)]
    lows = [10.0 + i * 0.1 - 2.0 for i in range(n)]
    closes = [10.0 + i * 0.1 for i in range(n)]
    k, d = stoch(highs, lows, closes)
    assert k[12] is None and k[13] == pytest.approx(100.0)
    assert k[-1] == pytest.approx(100.0)
    assert d[14] is None and d[15] == pytest.approx(100.0)


# ------------------------------------------------------------ SQL rebuilds

def test_prices_daily_types_and_returns(warehouse):
    bars = [
        {"ticker": "AAPL", "date": date(2026, 6, 1), "open": "10", "high": "12", "low": "9", "close": "11", "volume": "100"},
        {"ticker": "AAPL", "date": date(2026, 6, 2), "open": "11", "high": "13", "low": "10", "close": "12", "volume": "200"},
    ]
    _seed_bars(warehouse, "AAPL", bars)
    rows = warehouse.connect(read_only=True).execute(
        "SELECT date, open, close, volume, return_1d FROM staging.stg_prices_daily ORDER BY date"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0] == (date(2026, 6, 1), 10.0, 11.0, 100.0, None)
    assert rows[1][4] == pytest.approx(12.0 / 11.0 - 1)


def test_prices_daily_drops_hole_bars(warehouse):
    bars = [
        {"ticker": "AAPL", "date": date(2026, 6, 1), "open": "10", "high": "12", "low": "9", "close": "11", "volume": "100"},
        {"ticker": "AAPL", "date": date(2026, 6, 2), "open": None},  # hole: no OHLCV
    ]
    _seed_bars(warehouse, "AAPL", bars)
    count = warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM staging.stg_prices_daily"
    ).fetchone()[0]
    assert count == 1


def test_weekly_resample_iso_weeks(warehouse):
    bars = [
        {"ticker": "AAPL", "date": W1, "open": "10", "high": "12", "low": "8", "close": "11", "volume": "100"},
        {"ticker": "AAPL", "date": date(2026, 6, 3), "open": "11", "high": "15", "low": "10", "close": "14", "volume": "200"},
        {"ticker": "AAPL", "date": W2, "open": "14", "high": "16", "low": "13", "close": "15", "volume": "300"},
    ]
    _seed_bars(warehouse, "AAPL", bars)
    rebuild_prices_weekly(warehouse, "AAPL")
    rows = warehouse.connect(read_only=True).execute(
        "SELECT date, open, high, low, close, volume FROM mart.m_prices_weekly ORDER BY date"
    ).fetchall()
    assert rows == [
        (W1, 10.0, 15.0, 8.0, 14.0, 300.0),  # first-open / max-high / min-low / last-close / sum-vol
        (W2, 14.0, 16.0, 13.0, 15.0, 300.0),
    ]


def test_monthly_resample(warehouse):
    bars = [
        {"ticker": "AAPL", "date": date(2026, 5, 29), "open": "1", "high": "2", "low": "1", "close": "2", "volume": "10"},
        {"ticker": "AAPL", "date": date(2026, 6, 1), "open": "2", "high": "4", "low": "1", "close": "3", "volume": "20"},
        {"ticker": "AAPL", "date": date(2026, 6, 30), "open": "3", "high": "5", "low": "3", "close": "5", "volume": "30"},
    ]
    _seed_bars(warehouse, "AAPL", bars)
    rebuild_prices_monthly(warehouse, "AAPL")
    rows = warehouse.connect(read_only=True).execute(
        "SELECT date, open, close, volume FROM mart.m_prices_monthly ORDER BY date"
    ).fetchall()
    assert rows == [
        (date(2026, 5, 1), 1.0, 2.0, 10.0),
        (date(2026, 6, 1), 2.0, 5.0, 50.0),
    ]


def test_advanced_analytics_drawdown(warehouse):
    bars = [
        {"ticker": "AAPL", "date": date(2026, 6, 1 + i), "open": str(v), "high": str(v + 1), "low": str(v - 1), "close": str(v), "volume": "10"}
        for i, v in enumerate([100, 120, 90, 110])
    ]
    _seed_bars(warehouse, "AAPL", bars)
    rebuild_advanced_analytics(warehouse, "AAPL")
    row = warehouse.connect(read_only=True).execute(
        "SELECT close, min_252, max_252, max_drawdown_252, min_all, max_all, mean_all "
        "FROM mart.m_advanced_analytics WHERE date = ?",
        [date(2026, 6, 3)],  # the 90-bar: 90/120 - 1
    ).fetchone()
    assert row[0] == 90.0
    assert row[1] == 90.0 and row[2] == 120.0
    assert row[3] == pytest.approx(90.0 / 120.0 - 1)
    assert row[4] == 90.0 and row[5] == 120.0
    assert row[6] == pytest.approx(105.0)


# ---------------------------------------------------------- indicators rows

def test_technical_indicators_pipeline(warehouse):
    # 30 bars of a steady ramp: closes 100.5..129.5, spread {v-1, v+1}, const volume
    bars = []
    for i in range(30):
        v = 100.0 + i
        bars.append({
            "ticker": "AAPL",
            "date": date(2026, 5, 1 + i),
            "open": str(v - 0.5), "high": str(v + 1), "low": str(v - 1),
            "close": str(v + 0.5), "volume": "100",
        })
    _seed_bars(warehouse, "AAPL", bars)
    rebuild_technical_indicators(warehouse, "AAPL")

    con = warehouse.connect(read_only=True)
    cols = con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='mart' AND table_name='m_technical_indicators' ORDER BY ordinal_position").fetchall()
    col_names = [c[0] for c in cols]
    row = con.execute(
        "SELECT * FROM mart.m_technical_indicators WHERE date = ?", [date(2026, 5, 30)]
    ).fetchone()
    d = dict(zip(col_names, row))

    assert d["sma_20"] == pytest.approx(120.0)     # last 20 closes 110.5..129.5
    assert d["sma_200"] is None                    # only 30 bars loaded
    assert d["rsi_14"] == pytest.approx(100.0)      # every close higher than prior
    assert d["cci_20"] is not None and d["cci_20"] > 0  # monotonic ramp sits above its SMA
    assert d["adx_14"] == pytest.approx(100.0)      # pure +DM ramp, DX = 100 flat
    assert d["plus_di_14"] == pytest.approx(50.0)   # +DI = 100 * (+DM 1 / ATR 2)
    assert d["minus_di_14"] == pytest.approx(0.0)
    assert d["stoch_k_14"] is not None and 0.0 <= d["stoch_k_14"] <= 100.0
    assert d["stoch_d_14"] is not None and 0.0 <= d["stoch_d_14"] <= 100.0
    assert d["atr_14"] == pytest.approx(2.0)        # gap-free bars: TR = high - low = 2
    assert d["obv"] == pytest.approx(2900.0)        # 29 up-bars * 100 volume
    assert d["ad"] == pytest.approx(1450.0)         # +0.5 money-flow multiplier * 100 * 29
    assert d["bb_mid_20"] == d["sma_20"]
    assert d["bb_upper_20"] > d["bb_mid_20"] > d["bb_lower_20"]
    assert d["ema_12"] is not None and d["ema_26"] is not None
    assert d["macd_hist"] == pytest.approx(d["macd"] - d["macd_signal"])


def test_rebuild_counts_and_idempotency(warehouse):
    bars = [
        {"ticker": "AAPL", "date": date(2026, 6, 1), "open": "10", "high": "12", "low": "9", "close": "11", "volume": "100"},
        {"ticker": "AAPL", "date": date(2026, 6, 2), "open": "11", "high": "13", "low": "10", "close": "12", "volume": "200"},
    ]
    _seed_bars(warehouse, "AAPL", bars)
    rebuild_prices_weekly(warehouse, "AAPL")
    rebuild_technical_indicators(warehouse, "AAPL")

    first = warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM mart.m_technical_indicators"
    ).fetchone()[0]
    rebuild_technical_indicators(warehouse, "AAPL")
    second = warehouse.connect(read_only=True).execute(
        "SELECT COUNT(*) FROM mart.m_technical_indicators"
    ).fetchone()[0]
    assert first == 2 and second == 2  # delete-then-rebuild, not append