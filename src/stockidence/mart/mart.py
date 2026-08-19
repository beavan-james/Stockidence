"""Mart aggregates & indicators, rebuilt per ticker from the staged bars.

Mart holds everything that aggregates over bars — the scoring layer reads
only this layer. Built from staging.stg_prices_daily, never from raw.

Layer rule — staging cleans, mart aggregates:
  - resamples (weekly/monthly OHLCV)
  - rolling 252-bar stats + max drawdown (m_advanced_analytics)
  - indicator series (m_technical_indicators)

None of this hits an API (registry cadence DERIVED). Every rebuild is a full
per-ticker recompute: delete the ticker's rows, rebuild from staged bars.
That keeps the layer idempotent by construction and immune to Twelve Data's
occasional historical-bar revisions (a backfill or split adjustment simply
flows through next run).

Split of labor:
  - SQL: resample + rolling stats (window functions).
  - Python (pure per-bar series math): SMA/EMA/MACD, RSI, ATR, ADX, CCI,
    BBANDS, AD, OBV — Wilder-style recursive smoothing that window
    functions can't express cleanly.
"""

from __future__ import annotations

from typing import Any

from ..staging.staging import rebuild_prices_daily
from ..storage import Warehouse


def _rebuild_resample(warehouse: Warehouse, table: str, bucket: str, ticker: str) -> int:
    with warehouse.connect() as con:
        con.execute(f"DELETE FROM mart.{table} WHERE ticker = ?", [ticker])
        con.execute(
            f"""
            INSERT INTO mart.{table} (ticker, date, open, high, low, close, volume)
            SELECT
                ticker,
                CAST(date_trunc('{bucket}', date) AS DATE),
                first(open  ORDER BY date),
                MAX(high),
                MIN(low),
                last(close ORDER BY date),
                SUM(volume)
            FROM staging.stg_prices_daily
            WHERE ticker = ?
            GROUP BY ticker, CAST(date_trunc('{bucket}', date) AS DATE)
            """,
            [ticker],
        )
        return con.execute(
            f"SELECT COUNT(*) FROM mart.{table} WHERE ticker = ?", [ticker]
        ).fetchone()[0]


def rebuild_prices_weekly(warehouse: Warehouse, ticker: str) -> int:
    """ISO-week resample (weeks start Monday) of the clean daily bars → mart."""
    return _rebuild_resample(warehouse, "m_prices_weekly", "week", ticker)


def rebuild_prices_monthly(warehouse: Warehouse, ticker: str) -> int:
    return _rebuild_resample(warehouse, "m_prices_monthly", "month", ticker)


def rebuild_advanced_analytics(warehouse: Warehouse, ticker: str) -> int:
    """Rolling 252-trading-day stats + since-inception stats per bar → mart.

    max_drawdown_252 is the deepest close-to-running-peak trough inside the
    trailing 252-bar window (negative; 0.0 when the bar is at its window peak).
    """
    with warehouse.connect() as con:
        con.execute("DELETE FROM mart.m_advanced_analytics WHERE ticker = ?", [ticker])
        con.execute(
            """
            INSERT INTO mart.m_advanced_analytics
                (ticker, date, close, min_252, max_252, mean_252, stddev_252,
                 variance_252, max_drawdown_252, min_all, max_all, mean_all)
            WITH per_bar AS (
                SELECT
                    ticker, date, close,
                    MIN(close) OVER w252 AS min_252,
                    MAX(close) OVER w252 AS max_252,
                    AVG(close) OVER w252 AS mean_252,
                    STDDEV_SAMP(close) OVER w252 AS stddev_252,
                    VARIANCE(close) OVER w252 AS variance_252,
                    MAX(close) OVER w252 AS peak_252,
                    MIN(close) OVER w_bar AS min_all,
                    MAX(close) OVER w_bar AS max_all,
                    AVG(close) OVER w_bar AS mean_all
                FROM staging.stg_prices_daily
                WHERE ticker = ?
                WINDOW
                    w252 AS (PARTITION BY ticker ORDER BY date
                             ROWS BETWEEN 251 PRECEDING AND CURRENT ROW),
                    w_bar AS (PARTITION BY ticker)
            )
            SELECT
                ticker, date, close, min_252, max_252, mean_252, stddev_252,
                variance_252,
                MIN(close / peak_252 - 1) OVER w252 AS max_drawdown_252,
                min_all, max_all, mean_all
            FROM per_bar
            WINDOW w252 AS (PARTITION BY ticker ORDER BY date
                            ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
            ORDER BY date
            """,
            [ticker],
        )
        return con.execute(
            "SELECT COUNT(*) FROM mart.m_advanced_analytics WHERE ticker = ?", [ticker]
        ).fetchone()[0]


# ------------------------------------------------------- recursive indicators

def ema(values: list[float], span: int) -> list[float | None]:
    """Exponential moving average seeded with the first value (standard)."""
    if not values:
        return []
    k = 2.0 / (span + 1)
    out: list[float | None] = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI. None before `period` bars of changes have accumulated."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out: list[float | None] = [None] * (period + 1)
    for i in range(period, len(gains)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    return out


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder-smoothed average true range. None until `period` true ranges."""
    if len(highs) < period + 1:
        return [None] * len(highs)
    trs: list[float] = []
    for i in range(1, len(highs)):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    seed = sum(trs[:period]) / period
    out: list[float | None] = [None] * (period + 1)
    out.append(seed)
    for tr in trs[period:]:
        seed = (seed * (period - 1) + tr) / period
        out.append(seed)
    return out


def adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder ADX. None for the first 2*period - 1 bars (DM/ATR smoothing
    seeds at bar `period`, then DX needs `period` values to seed ADX)."""
    n = len(highs)
    if n < 2 * period:
        return [None] * n
    up = [highs[i] - highs[i - 1] for i in range(1, n)]
    down = [lows[i - 1] - lows[i] for i in range(1, n)]
    plus_dm = [u if (u > d and u > 0) else 0.0 for u, d in zip(up, down)]
    minus_dm = [d if (d > u and d > 0) else 0.0 for u, d in zip(up, down)]
    trs: list[float] = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))

    def wilder(series: list[float]) -> list[float]:
        seed = sum(series[:period]) / period
        out = [seed]
        for v in series[period:]:
            out.append((out[-1] * (period - 1) + v) / period)
        return out

    # smoothed series are indexed by bar (period + i); DX shares that index
    atr_s = wilder(trs)
    pdm = wilder(plus_dm)
    mdm = wilder(minus_dm)
    dx = [0.0] * len(atr_s)
    for i, t in enumerate(atr_s):
        s = pdm[i] + mdm[i]
        dx[i] = 0.0 if s == 0 else 100.0 * abs(pdm[i] - mdm[i]) / s

    # ADX is Wilder-smoothed DX; its j-th value belongs to bar 2*period - 1 + j
    adx_s = wilder(dx)
    out: list[float | None] = [None] * n
    for j, v in enumerate(adx_s):
        out[2 * period - 1 + j] = v
    return out


def cci(highs: list[float], lows: list[float], closes: list[float], period: int = 20) -> list[float | None]:
    """Commodity Channel Index. 0.0 where the mean deviation is zero."""
    n = len(highs)
    if n < period:
        return [None] * n
    tp = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    out: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, n):
        window = tp[i - period + 1: i + 1]
        sma = sum(window) / period
        mdev = sum(abs(x - sma) for x in window) / period
        out.append(0.0 if mdev == 0 else (tp[i] - sma) / (0.015 * mdev))
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    running_sum = 0.0
    for i, v in enumerate(values):
        running_sum += v
        if i >= period:
            running_sum -= values[i - period]
        out.append(running_sum / period if i >= period - 1 else None)
    return out


def _bbands(closes: list[float], period: int = 20, k: float = 2.0) -> tuple[list[float | None], ...]:
    """Bollinger bands (mid = SMA, width = k * population stddev)."""
    mid = sma(closes, period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1: i + 1]
        m = mid[i]
        assert m is not None
        var = sum((x - m) ** 2 for x in window) / period
        band = k * var ** 0.5
        upper[i] = m + band
        lower[i] = m - band
    return upper, mid, lower


def _obv_and_ad(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[float],
) -> tuple[list[float], list[float]]:
    """Cumulative On-Balance Volume and Accumulation/Distribution for ordered bars."""
    obv: list[float] = [0.0]
    money: list[float] = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
        range_ = highs[i] - lows[i]
        mf = volumes[i] if range_ == 0 else volumes[i] * ((closes[i] - lows[i]) - (highs[i] - closes[i])) / range_
        money.append(money[-1] + mf)
    return obv, money


def rebuild_technical_indicators(warehouse: Warehouse, ticker: str) -> int:
    """SMA/BBANDS/EMA/MACD/RSI/ATR/ADX/CCI/AD/OBV — one row per trading day → mart.

    Indicators are computed for every bar (None before an indicator's
    warm-up period). The recursive/Wilder series (EMA/MACD/RSI/ATR/ADX/CCI)
    and the cumulative/summation series (SMA/BBANDS/OBV/AD) are computed
    here from stg_prices_daily bars and inserted in one pass.
    """
    row = warehouse.connect(read_only=True).execute(
        """
        SELECT date, open, high, low, close, volume
        FROM staging.stg_prices_daily
        WHERE ticker = ?
        ORDER BY date
        """,
        [ticker],
    ).fetchall()
    if not row:
        with warehouse.connect() as con:
            con.execute("DELETE FROM mart.m_technical_indicators WHERE ticker = ?", [ticker])
        return 0

    dates = [r[0] for r in row]
    highs, lows, closes, volumes = ([r[i] for r in row] for i in range(2, 6))

    ema_12, ema_26 = ema(closes, 12), ema(closes, 26)
    macd = [a - b if a is not None and b is not None else None for a, b in zip(ema_12, ema_26)]
    signal = ema([m for m in macd if m is not None], 9)
    sig_it = iter(signal)
    macd_signal = [next(sig_it) if m is not None else None for m in macd]

    obv, money = _obv_and_ad(closes, highs, lows, volumes)
    r = rsi(closes)
    a = atr(highs, lows, closes)
    dx_ = adx(highs, lows, closes)
    ch = cci(highs, lows, closes)
    sma_20, sma_50 = sma(closes, 20), sma(closes, 50)
    bb_upper, bb_mid, bb_lower = _bbands(closes)

    rows = [
        [ticker, dates[i], sma_20[i], sma_50[i], ema_12[i], ema_26[i], macd[i], macd_signal[i],
         macd[i] - macd_signal[i] if macd[i] is not None and macd_signal[i] is not None else None,
         r[i], a[i], dx_[i], ch[i], money[i], obv[i], bb_upper[i], bb_mid[i], bb_lower[i]]
        for i in range(len(dates))
    ]
    with warehouse.connect() as con:
        con.execute("DELETE FROM mart.m_technical_indicators WHERE ticker = ?", [ticker])
        for r in rows:
            con.execute(
                """
                INSERT INTO mart.m_technical_indicators
                    (ticker, date, sma_20, sma_50, ema_12, ema_26, macd, macd_signal,
                     macd_hist, rsi_14, atr_14, adx_14, cci_20, ad, obv,
                     bb_upper_20, bb_mid_20, bb_lower_20)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                r,
            )
    return len(rows)


def rebuild_all_for_ticker(warehouse: Warehouse, ticker: str) -> dict[str, int]:
    """Run every staging & mart derivation for one ticker in dependency order."""
    return {
        "stg_prices_daily": rebuild_prices_daily(warehouse, ticker),
        "m_prices_weekly": rebuild_prices_weekly(warehouse, ticker),
        "m_prices_monthly": rebuild_prices_monthly(warehouse, ticker),
        "m_advanced_analytics": rebuild_advanced_analytics(warehouse, ticker),
        "m_technical_indicators": rebuild_technical_indicators(warehouse, ticker),
    }