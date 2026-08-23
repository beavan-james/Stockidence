"""Trade simulator rules on synthetic bars: every scenario has a hand-
computed expected fill/exit so the pessimism assumptions stay pinned."""

from datetime import date, timedelta

from stockidence.backtest import BacktestRow
from stockidence.backtest_trades import Trade, _simulate_one

D = date(2026, 1, 1)


def _bar(n, o, h, lo, c):
    """n-th bar after the epoch-ish start; n can exceed month length."""
    return (D + timedelta(days=n), float(o), float(h), float(lo), float(c))


def _signal(bar_n, rating="Strong Buy", buy=100.0, stop=90.0,
            target=115.0):
    return BacktestRow(
        ticker="T", as_of=D + timedelta(days=bar_n), rating=rating,
        confidence=67.0, volatility=40.0, category_scores={},
        fwd_returns={}, fwd_vols={},
        plan={"buy_price": buy, "stop_loss": stop,
              "target_price": target, "holding_style": "swing trade"},
    )


def test_limit_touch_fills_at_limit_then_target():
    bars = [_bar(1, 101, 102, 100, 101),   # signal day (close 101 > limit)
            _bar(2, 103, 104, 99.5, 100),  # dips to limit -> fill @100
            _bar(3, 100, 116, 100, 112),   # high hits target -> exit @115
            _bar(4, 111, 113, 110, 111)]
    ts = _simulate_one("T", [_signal(1)], bars, entry_ratings=("Strong Buy",),
                       entry_window=5, max_hold=60, cost_bps=0.0)
    assert len(ts) == 1
    t = ts[0]
    assert t.entry_price == 100.0
    assert t.entry_date == D + timedelta(days=2)
    assert t.exit_reason == "target" and t.exit_price == 115.0
    assert t.net_return == (115 / 100 - 1)


def test_gap_below_limit_fills_at_open():
    bars = [_bar(1, 101, 102, 100, 101),
            _bar(2, 97, 98, 96, 97),       # opens through the limit
            _bar(3, 97, 98, 95, 98)]
    ts = _simulate_one("T", [_signal(1)], bars, entry_ratings=("Strong Buy",),
                       entry_window=5, max_hold=60, cost_bps=0.0)
    assert ts[0].entry_price == 97.0


def test_stop_gap_down_exits_at_open_not_stop():
    # entry fills at limit on bar 2; bar 3 opens below the stop
    bars = [_bar(1, 101, 102, 100, 101),
            _bar(2, 103, 104, 99.5, 100),
            _bar(3, 85, 86, 84, 85)]
    ts = _simulate_one("T", [_signal(1)], bars, entry_ratings=("Strong Buy",),
                       entry_window=5, max_hold=60, cost_bps=0.0)
    t = ts[0]
    assert t.exit_reason == "stop" and t.exit_price == 85.0
    assert t.net_return == (85 / 100 - 1)


def test_timeout_and_costs_apply():
    bars = ([_bar(1, 101, 102, 100, 101),
             _bar(2, 103, 104, 99.5, 100)]
            + [_bar(3 + k, 100, 101, 99.8, 100) for k in range(60)])
    ts = _simulate_one("T", [_signal(1)], bars, entry_ratings=("Strong Buy",),
                       entry_window=5, max_hold=10, cost_bps=10.0)
    t = ts[0]
    assert t.exit_reason == "timeout" and t.days_held == 10
    assert abs(t.net_return - (0.0 - 10 / 10_000)) < 1e-12


def test_signal_during_position_ignored_then_reentry():
    bars = [_bar(1, 101, 102, 100, 101),
            _bar(2, 103, 104, 99.5, 100),   # trade 1 fills
            _bar(3, 100, 116, 100, 112),    # trade 1 exits at target
            _bar(4, 111, 112, 105, 106),
            _bar(5, 106, 107, 99, 100),     # trade 2 fills (signal bar 4)
            _bar(6, 100, 116, 100, 113)]    # trade 2 exits at target
    sigs = [_signal(1), _signal(4)]
    ts = _simulate_one("T", sigs, bars, entry_ratings=("Strong Buy",),
                       entry_window=5, max_hold=60, cost_bps=0.0)
    assert [t.exit_reason for t in ts] == ["target", "target"]
    assert ts[1].entry_date == D + timedelta(days=5)


def test_wrong_rating_or_missing_plan_never_enters():
    bars = [_bar(1, 101, 102, 100, 101), _bar(2, 99, 100, 95, 96)]
    no_plan = _signal(1, rating="Strong Buy")
    no_plan.plan = None
    hold_sig = _signal(1, rating="Hold")
    for sig in (no_plan, hold_sig):
        ts = _simulate_one("T", [sig], bars, entry_ratings=("Strong Buy",),
                           entry_window=5, max_hold=10, cost_bps=0.0)
        assert ts == []


def test_unfilled_limit_recorded():
    bars = [_bar(1, 101, 102, 100.5, 101),  # never touches 100
            _bar(2, 101, 102, 100.6, 102)]
    ts = _simulate_one("T", [_signal(1)], bars, entry_ratings=("Strong Buy",),
                       entry_window=2, max_hold=10, cost_bps=0.0)
    assert len(ts) == 1 and ts[0].exit_reason == "unfilled"
    assert ts[0].net_return is None


def test_apply_plan_params_rebuilds_geometry():
    from stockidence.backtest_trades import PlanParams, apply_plan_params
    row = _signal(1)
    row.plan.update({"signal_price": 100.0, "atr_14": 4.0,
                     "fair_value": 130.0})
    # defaults reproduce the stored plan exactly (buy=min(100, 110.5)=100,
    # stop=100-1.5*4=94 -> floored to 60? no: floor 0.6*100=60, stays 94)
    out = apply_plan_params([row], PlanParams())[0].plan
    assert out["buy_price"] == 100.0
    assert out["stop_loss"] == 94.0
    # wider stop: scale 2 -> 100 - 3*4 = 88 (above the 60 floor)
    out = apply_plan_params([row], PlanParams(atr_scale=2.0))[0].plan
    assert out["stop_loss"] == 88.0
    # deeper margin of safety pulls the limit below market: 130*0.85=110>100,
    # so mos must bite: 130*(1-0.30)=91 -> buy 91, stop 91-6=85, floor 54.6
    out = apply_plan_params([row], PlanParams(mos=0.30))[0].plan
    assert abs(out["buy_price"] - 91.0) < 1e-9
    assert abs(out["stop_loss"] - 85.0) < 1e-9
    # target_mode=fv swaps the exit for fair value
    out = apply_plan_params([row], PlanParams(target_mode="fv"))[0].plan
    assert out["target_price"] == 130.0
