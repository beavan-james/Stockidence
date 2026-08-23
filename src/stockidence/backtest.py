"""Backtest harness: replay point-in-time scores vs subsequent returns.

For each replay date we re-run the deterministic scorer with as_of set, so
bar-dated inputs cannot see the future, then record what actually happened
over the next N trading days. The output feeds tuning conversations about
MODEL.md weights/thresholds — this module only measures; it never mutates
the model or the mart snapshot tables (score_ticker runs persist=False).

Known approximation: slow period-keyed inputs (quarterly fundamentals,
monthly insider/analyst snapshots, transcripts) are used as-landed rather
than as-of-publication, because free-tier sources don't expose reliable
report timestamps. These move slowly enough that lookahead risk is small;
flag it in any writeup of results.

Usage:
    uv run python -m stockidence.backtest --tickers AAPL,MSFT \
        --start 2025-01-01 --end 2026-06-30 --step-days 7
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from .mart.scoring import score_ticker
from .storage import Warehouse

BULLISH = ("Strong Buy", "Buy")
BEARISH = ("Sell", "Strong Sell")

MIN_BARS = 210  # ~ SMA200 + slack, so trend components aren't all-neutral


@dataclass
class BacktestRow:
    ticker: str
    as_of: date
    rating: str
    confidence: float
    volatility: float
    category_scores: dict[str, float]
    fwd_returns: dict[int, float]
    fwd_vols: dict[int, float]


@dataclass
class Summary:
    horizon: int
    rating: str
    n: int
    directional_accuracy: float
    mean_return: float
    median_return: float


def _trading_bars(con: Any, ticker: str,
                  start: date | None, end: date | None) -> list[tuple[date, float]]:
    """Chronological [(date, close)] bars, optionally windowed."""
    rows = con.execute(
        """
        SELECT date, close FROM staging.stg_prices_daily
        WHERE ticker = ? AND close IS NOT NULL
        ORDER BY date
        """,
        [ticker],
    ).fetchall()
    out = [(r[0], r[1]) for r in rows]
    lo = start or date.min
    hi = end or date.max
    return [(d, c) for d, c in out if lo <= d <= hi]


def run_backtest(
    warehouse: Warehouse,
    tickers: list[str],
    start: date | None = None,
    end: date | None = None,
    step_days: int = 7,
    horizons: tuple[int, ...] = (5, 20, 60),
    min_bars: int = MIN_BARS,
) -> list[BacktestRow]:
    """Replay scores every `step_days` trading bars per ticker.

    An as_of needs `min_bars` prior bars (so indicators aren't degenerate)
    and `max(horizons)` subsequent bars (so every forward return exists);
    otherwise the snapshot is skipped rather than scored on thin data.
    """
    rows: list[BacktestRow] = []
    need_future = max(horizons)
    with warehouse.connect() as con:
        for ticker in tickers:
            bars = _trading_bars(con, ticker, start, end)
            eligible = [
                i for i in range(len(bars))
                if i >= min_bars and i + need_future < len(bars)
            ]
            print(f"[{ticker}] {len(bars)} bars, "
                  f"{len(eligible)} replay dates (min_bars={min_bars}, "
                  f"need_future={need_future})")
            for i in eligible[::step_days]:
                as_of = bars[i][0]
                result = score_ticker(warehouse, ticker, as_of=as_of,
                                      now=datetime(as_of.year, as_of.month,
                                                   as_of.day,
                                                   tzinfo=timezone.utc),
                                      persist=False)
                fwd = {}
                fvol = {}
                for h in horizons:
                    entry, exit_ = bars[i], bars[i + h]
                    fwd[h] = exit_[1] / entry[1] - 1.0
                    # realized forward volatility: stdev of the daily returns
                    # inside the horizon window (per-bar; scale-invariant to
                    # annualization, which correlation ignores anyway)
                    rets = [bars[i + k + 1][1] / bars[i + k][1] - 1.0
                            for k in range(h)]
                    fvol[h] = statistics.pstdev(rets) if h > 1 else 0.0
                rows.append(BacktestRow(
                    ticker=ticker,
                    as_of=as_of,
                    rating=result.rating,
                    confidence=result.confidence_score,
                    volatility=result.volatility_score,
                    category_scores={c.name: c.score
                                     for c in result.categories},
                    fwd_returns=fwd,
                    fwd_vols=fvol,
                ))
    return rows


def summarize(rows: list[BacktestRow], horizons: tuple[int, ...] = (5, 20, 60)
              ) -> list[Summary]:
    """Directional accuracy + realized return per (rating, horizon).

    Directional expectation is defined by the product framing: Buy-rated
    tickers should rise; Sell-rated should fall. Hold carries no direction
    and is reported but never counted toward accuracy.
    """
    out: list[Summary] = []
    by_rating: dict[str, list[BacktestRow]] = {}
    for r in rows:
        by_rating.setdefault(r.rating, []).append(r)
    for horizon in horizons:
        for rating in (*BULLISH, *BEARISH, "Hold"):
            group = by_rating.get(rating, [])
            if not group:
                continue
            rets = [r.fwd_returns[horizon] for r in group]
            want_up = rating in BULLISH
            hits = sum(1 for x in rets if (x > 0) == want_up)
            out.append(Summary(
                horizon=horizon,
                rating=rating,
                n=len(rets),
                directional_accuracy=hits / len(rets),
                mean_return=statistics.fmean(rets),
                median_return=statistics.median(rets),
            ))
    return out


def render(rows: list[BacktestRow], horizons: tuple[int, ...] = (5, 20, 60)) -> str:
    """Plain-text report suitable for pasting into a tuning discussion."""
    lines: list[str] = []
    total = len(rows)
    span = (min((r.as_of for r in rows), default=None),
            max((r.as_of for r in rows), default=None))
    lines.append(f"replays={total} span={span[0]}..{span[1]} "
                 f"tickers={len({r.ticker for r in rows})}")
    if not rows:
        lines.append("no eligible replay dates (need min_bars before and "
                     "max horizon after each as_of)")
        return "\n".join(lines)
    conf = [r.confidence for r in rows]
    lines.append(f"confidence mean={statistics.fmean(conf):.1f} "
                 f"stdev={statistics.pstdev(conf):.1f} "
                 f"min={min(conf):.1f} max={max(conf):.1f}")
    counts = {}
    for r in rows:
        counts[r.rating] = counts.get(r.rating, 0) + 1
    lines.append("rating mix: " + ", ".join(
        f"{k}={v}" for k, v in sorted(counts.items())))
    header = f"{'rating':<12}{'n':>5}"
    for h in horizons:
        header += f"   {'acc ' + str(h) + 'd':>9}{'ret ' + str(h) + 'd':>10}"
    lines.append(header)
    idx = {(s.rating, s.horizon): s for s in summarize(rows, horizons)}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.rating] = counts.get(r.rating, 0) + 1
    for rating in (*BULLISH, *BEARISH, "Hold"):
        if not any((rating, h) in idx for h in horizons):
            continue
        line = f"{rating:<12}{counts.get(rating, 0):>5}"
        for h in horizons:
            s = idx.get((rating, h))
            if s is not None:
                line += f"   {s.directional_accuracy:>8.0%}{s.mean_return:>10.2%}"
            else:
                line += f"   {'-':>19}"
        lines.append(line)
    return "\n".join(lines)


def save_rows(rows: list[BacktestRow], path: str) -> None:
    """Persist replay rows as JSON so diagnostics/tuning iterate without
    re-running the (expensive) score replays."""
    import json
    payload = [
        {
            "ticker": r.ticker,
            "as_of": r.as_of.isoformat(),
            "rating": r.rating,
            "confidence": r.confidence,
            "volatility": r.volatility,
            "category_scores": r.category_scores,
            "fwd_returns": {str(k): v for k, v in r.fwd_returns.items()},
            "fwd_vols": {str(k): v for k, v in r.fwd_vols.items()},
        }
        for r in rows
    ]
    with open(path, "w") as f:
        json.dump(payload, f)


def load_rows(path: str) -> list[BacktestRow]:
    import json
    with open(path) as f:
        payload = json.load(f)
    return [
        BacktestRow(
            ticker=p["ticker"],
            as_of=date.fromisoformat(p["as_of"]),
            rating=p["rating"],
            confidence=p["confidence"],
            volatility=p["volatility"],
            category_scores=p["category_scores"],
            fwd_returns={int(k): v for k, v in p["fwd_returns"].items()},
            fwd_vols={int(k): v for k, v in p["fwd_vols"].items()},
        )
        for p in payload
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--tickers", required=True,
                        help="comma-separated tickers, e.g. AAPL,MSFT")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--step-days", type=int, default=7,
                        help="replay every Nth eligible trading bar")
    parser.add_argument("--db", default=None, help="warehouse path override")
    parser.add_argument("--save", default=None,
                        help="write replay rows to this JSON path")
    args = parser.parse_args()
    warehouse = Warehouse(args.db)
    rows = run_backtest(
        warehouse,
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()],
        start=args.start, end=args.end, step_days=args.step_days,
    )
    print(render(rows))
    if args.save:
        save_rows(rows, args.save)
        print(f"rows saved to {args.save}")


if __name__ == "__main__":
    main()
