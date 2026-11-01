"""Walk-forward comparison behind the Stocks of the Week target choice.

Ranks the same weekly Friday-close cohorts with four variants, next-week vs
next-quarter (13-week) target crossed with the quarterly model's 13 inputs vs
those plus 13 short-horizon signals, and grades every variant on BOTH
horizons, so a model trained for one horizon is judged on the other too.
Every variant is tested on the same weeks: rows whose next-week outcome is
known, with all of that variant's inputs present.

Uses the production functions in stockidence.weekly (same fit, purge and
quarterly refit schedule), so the shipped variant's numbers match the
weekly job's walk-forward.

    python Model/scripts/compare_weekly_targets.py [--parquet PATH] [--variants a,b]

Reads Model/datasets/train_dataset_weekly.parquet by default (written by the
weekly_rank job, or by build_dataset.py --freq weekly).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from stockidence import weekly

SHORT = [
    "return_1w", "return_4w", "rsi_14", "price_to_sma20", "price_to_sma50",
    "stoch_k_14", "cci_20", "adx_14", "macd_hist_pct", "bb_pctb",
    "volume_ratio_13w", "range_1w", "vol_ratio",
]
# name -> (target column, horizon in weeks, inputs)
VARIANTS = {
    "next_week_core13": ("target_return", 1, weekly.FEATURES),
    "next_quarter_core13": ("target_return_13w", 13, weekly.FEATURES),
    "next_week_plus_short": ("target_return", 1, weekly.FEATURES + SHORT),
    "next_quarter_plus_short": ("target_return_13w", 13, weekly.FEATURES + SHORT),
}


def _t(s: pd.Series) -> float:
    s = s.dropna()
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))


def grade(scored: pd.DataFrame, bench: pd.DataFrame) -> dict:
    """Head-of-list metrics on both horizons for one variant's scores."""
    w1 = weekly.weekly_results(scored, bench["target_return"], "target_return")
    w13 = weekly.weekly_results(scored, bench["target_return_13w"], "target_return_13w")
    ex1 = w1["top10"] - w1["universe"]
    ex13 = w13["top10"] - w13["universe"]
    vs1 = (w1["top10"] - w1["spx"]).dropna()
    weeks = len(w1)
    return {
        "weeks": weeks,
        "ic_1w": w1["ic"].mean(),
        "top10_vs_list_1w_bp": ex1.mean() * 1e4,
        "t_1w": _t(ex1),
        "hit_1w": (ex1 > 0).mean(),
        "top10_vs_spx_1w_bp": vs1.mean() * 1e4,
        "beat_spx_1w": (vs1 > 0).mean(),
        "top10_vs_list_13w_pp": ex13.mean() * 100,
        # 13-week outcomes overlap week to week: t-stat on every 13th week.
        "t_13w": _t(ex13.iloc[::13]),
        # Rebalanced weekly, equal weight, no trading costs.
        "annual_top10_1w": (1 + w1["top10"]).prod() ** (52 / weeks) - 1,
        "annual_spx_1w": (1 + w1["spx"].fillna(0)).prod() ** (52 / weeks) - 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--parquet", type=Path, default=weekly.TRAIN_PARQUET)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    args = parser.parse_args()

    df = pd.read_parquet(args.parquet)
    df["date"] = pd.to_datetime(df["date"])
    bench = df[df["ticker"] == weekly.BENCHMARK].set_index("date")[
        ["target_return", "target_return_13w"]]

    rows = []
    for name in args.variants.split(","):
        target, horizon, features = VARIANTS[name]
        md = weekly.training_frame(df, "target_return", features)
        scored = weekly.walk_forward(md, target, features, horizon)
        scored = scored.merge(md[["date", "ticker", "target_return_13w"]], how="left") \
            if "target_return_13w" not in scored else scored
        rows.append({"variant": name, **grade(scored, bench)})
        print(f"{name}: {rows[-1]['weeks']} weeks", flush=True)

    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
