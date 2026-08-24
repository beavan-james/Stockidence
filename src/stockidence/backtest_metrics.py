"""Diagnostics for backtest replay rows: does the score rank-order outcomes?

The rating-bucket table answers "did Buy beat Hold"; tuning decisions need
the continuous view — Spearman rank correlation between confidence and
forward return, quintile monotonicity, and uncertainty that respects the
overlap problem (13 tickers replayed on the same weekly dates are not 431
independent observations, so confidence intervals bootstrap *dates*).

Also measures what the weights implicitly claim: each category sub-score's
own correlation with forward returns. If sentiment correlates and valuation
doesn't, moving weight from valuation to sentiment is evidence-led; doing
it the other way around is overfitting.

Everything here is a pure function of BacktestRow lists — no warehouse, no
network — so it runs instantly against cached rows (backtest.py --save).
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

from .backtest import BacktestRow


def _avg_ranks(xs: list[float]) -> list[float]:
    """Ranks 1..n with ties assigned their average rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation over average ranks; None-safe via guard."""
    n = len(xs)
    if n < 3 or len(ys) != n:
        return float("nan")
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx)
           * sum((b - my) ** 2 for b in ry)) ** 0.5
    if den == 0:
        return float("nan")
    return num / den


@dataclass
class Quintiles:
    means: list[float]          # mean forward return per confidence bin, low→high
    counts: list[int]
    monotonic: bool             # non-decreasing within tiny float tolerance


@dataclass
class Diagnostics:
    horizon: int
    n: int
    rho_confidence: float
    ci_low: float               # 2.5th pct of date-block bootstrap
    ci_high: float              # 97.5th pct
    excludes_zero: bool
    quintiles: Quintiles
    split_first: float          # Spearman in first calendar half
    split_second: float         # second half
    rho_volatility: float       # vol score vs realized fwd vol proxy
    category_rho: dict[str, float]
    category_ci: dict[str, tuple[float, float]]


def _pairs(rows: list[BacktestRow], key: str, horizon: int,
           realized: bool = False) -> tuple[list[float], list[float]]:
    """(score, outcome) pairs. `realized` swaps the outcome from forward
    return to realized forward volatility (for validating the vol score)."""
    xs, ys = [], []
    for r in rows:
        if horizon not in r.fwd_returns:
            continue
        x = (r.volatility if key == "volatility"
             else r.category_scores[key] if key in r.category_scores
             else r.confidence)
        y = r.fwd_vols[horizon] if realized else r.fwd_returns[horizon]
        xs.append(float(x))
        ys.append(float(y))
    return xs, ys


def quintiles(rows: list[BacktestRow], horizon: int = 60,
              bins: int = 5) -> Quintiles:
    """Mean forward return per confidence bin — is higher actually better?"""
    pts = sorted(((r.confidence, r.fwd_returns[horizon])
                  for r in rows if horizon in r.fwd_returns))
    n = len(pts)
    per, means, counts = n // bins, [], []
    for b in range(bins):
        lo = b * per
        hi = (b + 1) * per if b < bins - 1 else n
        chunk = pts[lo:hi]
        counts.append(len(chunk))
        means.append(statistics.fmean(y for _, y in chunk))
    tol = 1e-12
    mono = all(means[i + 1] >= means[i] - tol for i in range(bins - 1))
    return Quintiles(means=means, counts=counts, monotonic=mono)


def date_bootstrap_ci(rows: list[BacktestRow], horizon: int = 60,
                      key: str = "confidence", n_boot: int = 1000,
                      seed: int = 42,
                      alpha: float = 2.5) -> tuple[float, float]:
    """Percentile CI for a score's Spearman vs forward return, resampling
    whole replay dates so cross-ticker overlap doesn't fake significance."""
    by_date: dict[object, list[BacktestRow]] = {}
    for r in rows:
        if horizon in r.fwd_returns:
            by_date.setdefault(r.as_of, []).append(r)
    dates = sorted(by_date)
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        sample = [r for d in rng.choices(dates, k=len(dates))
                  for r in by_date[d]]
        rho = spearman(*_pairs(sample, key, horizon))
        if rho == rho:  # skip degenerate resamples (constant score)
            stats.append(rho)
    if not stats:
        return float("nan"), float("nan")
    stats.sort()
    lo_i = int(len(stats) * alpha / 100)
    hi_i = min(int(len(stats) * (100 - alpha) / 100), len(stats) - 1)
    return stats[lo_i], stats[hi_i]


def split_half(rows: list[BacktestRow], horizon: int = 60
               ) -> tuple[float, float]:
    """Spearman in each calendar half — does the edge survive regime drift?

    Splits by sorted row position, not date comparison, so replays sharing
    the median date can't collapse one half to empty.
    """
    ordered = sorted((r for r in rows if horizon in r.fwd_returns),
                     key=lambda r: r.as_of)
    n = len(ordered)
    if n < 4:
        return float("nan"), float("nan")
    half = n // 2
    return (spearman(*_pairs(ordered[:half], "confidence", horizon)),
            spearman(*_pairs(ordered[half:], "confidence", horizon)))


def diagnostics(rows: list[BacktestRow], horizon: int = 60,
                vol_horizon: int = 20, n_boot: int = 1000
                ) -> Diagnostics:
    q = quintiles(rows, horizon)
    rho = spearman(*_pairs(rows, "confidence", horizon))
    lo, hi = date_bootstrap_ci(rows, horizon, n_boot=n_boot)
    s1, s2 = split_half(rows, horizon)
    cats = sorted({c for r in rows for c in r.category_scores})
    cat_rho = {c: spearman(*_pairs(rows, c, horizon)) for c in cats}
    cat_ci = {c: date_bootstrap_ci(rows, horizon, key=c, n_boot=n_boot)
              for c in cats}
    return Diagnostics(
        horizon=horizon,
        n=len(rows),
        rho_confidence=rho,
        ci_low=lo,
        ci_high=hi,
        excludes_zero=bool(lo > 0 or hi < 0),
        quintiles=q,
        split_first=s1,
        split_second=s2,
        # the vol score's job is ranking turbulence, not direction — so it is
        # validated against realized forward volatility at a shorter horizon,
        # never against return and never folded into confidence
        rho_volatility=spearman(*_pairs(rows, "volatility", vol_horizon,
                                        realized=True)),
        category_rho=cat_rho,
        category_ci=cat_ci,
    )


def render_diag(d: Diagnostics) -> str:
    lines = [
        f"diagnostics @ {d.horizon}d (n={d.n})",
        f"  rho(confidence, fwd ret)   = {d.rho_confidence:+.3f} "
        f"[{d.ci_low:+.3f}, {d.ci_high:+.3f}] "
        f"{'excludes 0' if d.excludes_zero else 'INCLUDES 0'}",
        f"  quintile means ({d.quintiles.counts}): "
        + " ".join(f"{m:+.2%}" for m in d.quintiles.means)
        + ("  MONOTONIC" if d.quintiles.monotonic else "  NOT monotonic"),
        f"  split-half rho             = {d.split_first:+.3f} / "
        f"{d.split_second:+.3f}",
        f"  rho(volatility, fwd vol)   = {d.rho_volatility:+.3f}",
        "  category rho vs fwd ret:",
    ]
    for c, v in sorted(d.category_rho.items(),
                       key=lambda kv: kv[1], reverse=True):
        lo, hi = d.category_ci.get(c, (float("nan"), float("nan")))
        lines.append(f"    {c:<12} {v:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    return "\n".join(lines)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows_json", help="replay rows saved by backtest --save")
    parser.add_argument("--horizon", type=int, default=60)
    args = parser.parse_args()
    from .backtest import load_rows
    print(render_diag(diagnostics(load_rows(args.rows_json),
                                  horizon=args.horizon)))


if __name__ == "__main__":
    main()
