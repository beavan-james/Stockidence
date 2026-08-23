"""Trade-level backtest: turn replayed signals into round trips.

The rating-bucket and discrimination views measure *ranking* quality; this
module measures what the product actually promises — buy at the plan's
advised price, honor its stop-loss, take profit at the fair-value target,
and count the money. Signals come from cached replay rows (backtest.py
--save); fills are resolved against real OHLC bars so intrabar touches of
the limit or stop are honored, with gap rules that assume the worse fill:

  - entry: limit order at plan.buy_price, working for `entry_window` bars
    after the signal; fills at open if it gaps below the limit, else at the
    limit when touched. A fill day whose low breaches the stop stops out
    same day (pessimistic).
  - exits: stop checked before target within a bar (pessimistic); gaps
    through either level fill at the open.
  - timeout: flat at the close `max_hold` bars after entry, or end of data.
  - one position per ticker; signals during a position are ignored.

Round-trip costs (cost_bps) are deducted from every trade — a backtest
without them is marketing, not measurement.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass

from .backtest import BacktestRow, load_rows
from .storage import Warehouse

DEFAULT_ENTRY_RATINGS = ("Strong Buy",)
DEFAULT_ENTRY_WINDOW = 5
DEFAULT_MAX_HOLD = 60


@dataclass
class Trade:
    ticker: str
    signal_date: object
    entry_date: object | None
    entry_price: float | None
    exit_date: object | None
    exit_price: float | None
    net_return: float | None        # after costs; None while open/unfilled
    days_held: int | None
    exit_reason: str                # "stop" | "target" | "timeout" | "eod" | "unfilled"
    holding_style: str | None = None


def _simulate_one(ticker: str, signals: list[BacktestRow],
                  bars: list[tuple], *, entry_ratings: tuple[str, ...],
                  entry_window: int, max_hold: int,
                  cost_bps: float) -> list[Trade]:
    """bars: chronological (date, open, high, low, close)."""
    date_idx = {b[0]: i for i, b in enumerate(bars)}
    trades: list[Trade] = []
    pending = sorted(
        (r for r in signals if r.as_of in date_idx),
        key=lambda r: date_idx[r.as_of],
    )
    s = 0
    i = 0
    while i < len(bars) and s < len(pending):
        sig = pending[s]
        sb = date_idx[sig.as_of]
        if sb < i:          # signal already passed while we were positioned
            s += 1
            continue
        if sig.rating not in entry_ratings or not _plan_ok(sig):
            s += 1
            continue
        plan = sig.plan
        limit, stop = plan["buy_price"], plan["stop_loss"]
        target = plan.get("target_price")

        # --- entry phase --- (never fill on the very last bar: no exit left)
        filled_at = None
        for k in range(sb + 1, min(sb + entry_window, len(bars) - 2) + 1):
            d, o, h, lo, c = bars[k]
            if o <= limit:
                filled_at = (k, o)
                break
            if lo <= limit:
                filled_at = (k, limit)
                break
        if filled_at is None:
            trades.append(Trade(ticker, sig.as_of, None, None, None, None,
                                None, None, "unfilled", plan["holding_style"]))
            s += 1
            i = sb + 1
            continue

        ek, entry = filled_at

        # fill-day stop check (limit filled, then kept sliding to the stop)
        d, o, h, lo, c = bars[ek]
        exit_px = exit_day = None
        reason = None
        if lo <= stop:
            exit_px = min(o, stop) if o < stop else stop
            # gapped-through-stop open means we never got the limit either;
            # but o <= limit here means entry == open < stop -> instant stop
            exit_day, reason = ek, "stop"

        # --- holding phase ---
        if exit_day is None:
            for j in range(ek + 1, len(bars)):
                d, o, h, lo, c = bars[j]
                # intrabar stop beats timeout on the same bar (pessimistic)
                if lo <= stop:
                    exit_px = o if o < stop else stop
                    exit_day, reason = j, "stop"
                    break
                if target is not None and h >= target:
                    exit_px = o if o > target else target
                    exit_day, reason = j, "target"
                    break
                if j - ek >= max_hold:
                    exit_px, exit_day, reason = c, j, "timeout"
                    break
                if j == len(bars) - 1:
                    exit_px, exit_day, reason = c, j, "eod"
                    break

        gross = exit_px / entry - 1.0
        net = gross - cost_bps / 10_000.0
        trades.append(Trade(ticker, sig.as_of, bars[ek][0], entry,
                            bars[exit_day][0], exit_px, net,
                            exit_day - ek, reason, plan["holding_style"]))
        s += 1
        i = exit_day + 1     # no re-entry until the day after the exit
    return trades


def _plan_ok(row: BacktestRow) -> bool:
    p = row.plan
    return bool(p and p.get("buy_price") and p.get("stop_loss"))


def simulate(warehouse: Warehouse, rows: list[BacktestRow], *,
             entry_ratings: tuple[str, ...] = DEFAULT_ENTRY_RATINGS,
             entry_window: int = DEFAULT_ENTRY_WINDOW,
             max_hold: int = DEFAULT_MAX_HOLD,
             cost_bps: float = 5.0) -> list[Trade]:
    """Resolve cached signals against stored OHLC bars, ticker by ticker."""
    by_ticker: dict[str, list[BacktestRow]] = {}
    for r in rows:
        by_ticker.setdefault(r.ticker, []).append(r)
    trades: list[Trade] = []
    with warehouse.connect() as con:
        for ticker, sigs in by_ticker.items():
            bars = con.execute(
                """
                SELECT date, open, high, low, close
                FROM staging.stg_prices_daily
                WHERE ticker = ? AND close IS NOT NULL AND open IS NOT NULL
                ORDER BY date
                """,
                [ticker],
            ).fetchall()
            trades.extend(_simulate_one(
                ticker, sigs, bars,
                entry_ratings=entry_ratings, entry_window=entry_window,
                max_hold=max_hold, cost_bps=cost_bps))
    return [t for t in trades if t.entry_price is not None
            or t.exit_reason == "unfilled"]


def render_trades(trades: list[Trade]) -> str:
    lines: list[str] = []
    filled = [t for t in trades if t.net_return is not None]
    unfilled = [t for t in trades if t.exit_reason == "unfilled"]
    lines.append(f"signals={len(trades)} filled={len(filled)} "
                 f"unfilled={len(unfilled)}")
    if not filled:
        lines.append("no filled trades")
        return "\n".join(lines)
    rets = [t.net_return for t in filled]
    wins = sum(r > 0 for r in rets)
    reasons: dict[str, int] = {}
    for t in filled:
        reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
    compounded = 1.0
    for r in rets:
        compounded *= 1 + r
    lines.append(
        f"trades={len(filled)} win_rate={wins / len(filled):.0%} "
        f"avg={statistics.fmean(rets):+.2%} median={statistics.median(rets):+.2%} "
        f"best={max(rets):+.2%} worst={min(rets):+.2%}")
    lines.append(f"compounded x{compounded:.3f} "
                 f"avg_days_held={statistics.fmean(t.days_held for t in filled):.0f} "
                 f"exits={reasons} cost_bps_round_trip_deducted")
    lines.append("per-ticker:")
    for tkr in sorted({t.ticker for t in filled}):
        rs = [t.net_return for t in filled if t.ticker == tkr]
        lines.append(f"  {tkr:<6} n={len(rs):>2} avg={statistics.fmean(rs):+.2%} "
                     f"wins={sum(r > 0 for r in rs)}/{len(rs)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows_json", help="replay rows saved by backtest --save")
    parser.add_argument("--db", default=None, help="warehouse path override")
    parser.add_argument("--entry", default=",".join(DEFAULT_ENTRY_RATINGS),
                        help="ratings that trigger an entry, e.g. 'Strong Buy,Buy'")
    parser.add_argument("--entry-window", type=int, default=DEFAULT_ENTRY_WINDOW)
    parser.add_argument("--max-hold", type=int, default=DEFAULT_MAX_HOLD)
    parser.add_argument("--cost-bps", type=float, default=5.0,
                        help="round-trip transaction cost in basis points")
    args = parser.parse_args()
    warehouse = Warehouse(args.db)
    ratings = tuple(r.strip() for r in args.entry.split(",") if r.strip())
    trades = simulate(warehouse, load_rows(args.rows_json),
                      entry_ratings=ratings, entry_window=args.entry_window,
                      max_hold=args.max_hold, cost_bps=args.cost_bps)
    print(render_trades(trades))


if __name__ == "__main__":
    main()
