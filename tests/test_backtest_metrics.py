"""Metrics are pure functions of replay rows, so synthetic rows with known
rank structure pin exact behavior: perfect ordering → rho 1.0 and monotone
quintiles; shuffled outcomes → CI covering zero."""

import random

import pytest

from stockidence.backtest import BacktestRow
from stockidence.backtest_metrics import (
    diagnostics,
    quintiles,
    spearman,
    split_half,
)


def _row(conf: float, fwd60: float, vol_score: float = 50.0,
         as_of_day: int = 1) -> BacktestRow:
    return BacktestRow(
        ticker="FAKE",
        as_of=__import__("datetime").date(2026, 1, as_of_day),
        rating="Buy" if conf >= 60 else "Hold",
        confidence=conf,
        volatility=vol_score,
        category_scores={"valuation": conf * 0.8, "trend": conf * 0.6,
                         "sentiment": conf * 0.4, "moat": 50.0},
        fwd_returns={5: fwd60 / 10, 20: fwd60 / 2, 60: fwd60},
        fwd_vols={5: 0.01, 20: 0.02, 60: 0.03},
    )


def test_spearman_perfect_and_inverse():
    xs = [1, 2, 3, 4, 5]
    assert spearman(xs, [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman(xs, [50, 40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman(xs, [1, 5, 2, 4, 3]) == pytest.approx(0.3,
                                                          abs=1e-12)


def test_spearman_handles_ties_and_short_input():
    # ties share average ranks → still a perfect ordering
    assert spearman([1, 1, 2], [3, 3, 7]) == pytest.approx(1.0)
    # below n=3 (or zero variance) correlation is undefined
    assert spearman([1], [1]) != spearman([1], [1])
    assert spearman([5, 5, 5], [1, 2, 3]) != spearman([5, 5, 5], [1, 2, 3])


def test_quintiles_monotonic_on_ordered_signal():
    rows = [_row(40 + i, -10 + i * 5) for i in range(50)]
    q = quintiles(rows)
    assert q.monotonic
    assert q.means[-1] > q.means[0]


def test_quintiles_flags_inversion():
    # strong signal at the bottom bin only → non-monotone
    rows = ([_row(45 + i, 100) for i in range(10)]
            + [_row(55 + i, 1) for i in range(40)])
    assert not quintiles(rows).monotonic


def test_diagnostics_perfect_signal_excludes_zero():
    rows = [_row(40 + i, -15 + i, as_of_day=(i % 28) + 1) for i in range(56)]
    d = diagnostics(rows, horizon=60, n_boot=200)
    assert d.rho_confidence == pytest.approx(1.0)
    assert d.excludes_zero
    assert d.quintiles.monotonic
    # every category inherits the same perfect ordering except constant moat
    assert d.category_rho["moat"] != d.category_rho["moat"]  # nan
    assert max(v for k, v in d.category_rho.items()
               if k != "moat") == pytest.approx(1.0)
    # vol score was held constant → undefined correlation, not a wrong one
    assert d.rho_volatility != d.rho_volatility


def test_diagnostics_noise_includes_zero():
    rng = random.Random(7)
    rows = []
    for day in range(1, 29):
        for _ in range(4):
            c = rng.uniform(40, 70)
            r = rng.gauss(0, 10)
            rows.append(_row(c, r, vol_score=rng.uniform(30, 70),
                             as_of_day=day))
    d = diagnostics(rows, horizon=60, n_boot=300)
    assert not d.excludes_zero


def test_split_half_separates_calendar_periods():
    from datetime import date
    # 20 rows across two months; signal (conf ranks returns) present in both
    rows = []
    for i in range(10):
        r1 = _row(50 + i, i * 2, as_of_day=5)
        r2 = _row(50 + i, i * 3, as_of_day=20)
        r2.as_of = date(2026, 2, 20)
        rows += [r1, r2]
    s1, s2 = split_half(rows)
    assert s1 > 0.9 and s2 > 0.9
