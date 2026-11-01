"""Stocks of the Week pipeline steps (Dagster ops delegate here).

Chain, every Friday after the US close: refresh the whole ticker universe
(daily prices forced past the staleness gate, so every ticker lands Friday's
close) -> rebuild the weekly dataset -> refit the ranking model on every
closed week, walk it forward for the track record, rank this week's
snapshot -> export to mart.weekly_rankings and fill in how last week's list
did.

Same model family as the quarterly ranking (XGBoost rank:ndcg, quintile
grades per cohort). Model/README.md ("Stocks of the Week") is the spec and
records the target comparison that picked TARGET.

Heavy ML imports stay inside function bodies, as in quarterly.py, so
importing Dagster definitions never requires them.
"""

from __future__ import annotations

import importlib.util
import json
from typing import TYPE_CHECKING

from .config import repo_root
from .quarterly import quarterly_universe

if TYPE_CHECKING:
    import pandas as pd
    import xgboost as xgb

    from .storage import Warehouse

REPO_ROOT = repo_root()
BUILD_DATASET = REPO_ROOT / "Model" / "scripts" / "build_dataset.py"
DATASETS_DIR = REPO_ROOT / "Model" / "datasets"
ARTIFACTS_DIR = REPO_ROOT / "Model" / "artifacts"
# Every week whose next-week outcome is known (training + track record).
TRAIN_PARQUET = DATASETS_DIR / "train_dataset_weekly.parquet"
# This week's Friday-close snapshot: what the website list ranks.
SCORE_PARQUET = DATASETS_DIR / "score_dataset_weekly.parquet"
MODEL_NAME = "weekly_ranking"

# Next-week return, Monday open -> Friday close. Picked over the next-quarter
# target by the walk-forward comparison in Model/README.md.
TARGET = "target_return"
HORIZON_WEEKS = 1
# What a published list is graded on: the week it was published for.
OUTCOME = "target_return"

FEATURES = [
    "price_to_sma200", "stddev_252", "max_drawdown_252", "atr_pct",
    "return_3m", "return_12m", "distance_from_52wk_high",
    "roe", "roa", "debt_equity", "current_ratio", "cash_to_assets", "fcf_to_assets",
]

# S&P 500 benchmark, bought at the same Monday open as the picks. Refreshed
# with the universe, never ranked.
BENCHMARK = "VOO"
# Sparse/unusable history (same list as the quarterly model) + the benchmark.
EXCLUDED = frozenset({"AMBP", "BE", "BRK.B", "CRM", "FI", "NBIS", BENCHMARK})

PARAMS = {
    "objective": "rank:ndcg", "tree_method": "hist",
    "max_depth": 3, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8,
    "reg_alpha": 0.1, "reg_lambda": 1.0, "seed": 42, "nthread": -1,
}
N_ROUNDS = 150
N_GRADES = 5
TOP_K = 10
MIN_COHORT = 20
BACKTEST_START = "2019-01-01"


def _build_dataset_module():
    """Model/scripts/build_dataset.py, loaded by path (it isn't a package)."""
    spec = importlib.util.spec_from_file_location("build_dataset", BUILD_DATASET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot_date(label) -> str:
    """Weekly row label (Monday) -> its snapshot date (that week's Friday).

    The snapshot uses the week's last close (Thursday's on a holiday Friday);
    published dates are always the Friday so every weekly date lines up. The
    list ranks stocks for the week after it.
    """
    import pandas as pd

    return str((pd.Timestamp(label) + pd.Timedelta(days=4)).date())


def week_label(as_of) -> "pd.Timestamp":
    """Inverse of snapshot_date: Friday as_of -> the Monday row label."""
    import pandas as pd

    ts = pd.Timestamp(as_of)
    return ts - pd.Timedelta(days=ts.weekday())


def weekly_universe(warehouse: Warehouse | None = None) -> list[str]:
    """The quarterly refresh universe (every ticker in the warehouse) plus
    the benchmark ETF, which needs fresh bars to grade each list."""
    return list(dict.fromkeys(quarterly_universe(warehouse) + [BENCHMARK]))


# ── Dataset ─────────────────────────────────────────────────────────────────


def rebuild_weekly_dataset(now=None) -> dict:
    """Rebuild the weekly training parquet and this week's scoring cohort.

    `now` decides which week has closed (see build_dataset.last_closed_week):
    a Friday-evening run scores the week that just ended, a mid-week manual
    run scores the previous one. Only tickers whose last bar is the week's
    last close are scored, so a failed price fetch can't rank a stale
    snapshot; if that leaves under half the usual cohort, fail loudly and
    keep the current website list.
    """
    import pandas as pd

    from .storage import Warehouse

    bd = _build_dataset_module()
    full = bd.build_dataset(freq="weekly", keep_unlabeled=True, now=now)

    with Warehouse().connect(read_only=True) as con:
        newest = con.execute("SELECT MAX(date) FROM staging.stg_prices_daily").fetchone()[0]
        week = bd.last_closed_week(newest, now)
        closes = dict(con.execute(
            "SELECT ticker, MAX(date) FROM staging.stg_prices_daily"
            " WHERE date >= ? AND date < ? GROUP BY ticker",
            [week.date(), (week + pd.Timedelta(weeks=1)).date()],
        ).fetchall())
    if not closes:
        raise RuntimeError(f"no price bars in the week of {week.date()}; nothing to score")
    week_close = max(closes.values())
    fresh = {t for t, d in closes.items() if d == week_close}

    labeled = full[full[OUTCOME].notna()]
    score = full[(full["date"] == week) & full["ticker"].isin(fresh)]

    recent = int(labeled.groupby("date")["ticker"].nunique().tail(4).median())
    n_score = int(score["ticker"].nunique())
    if n_score < 0.5 * recent:
        stale = sorted(set(closes) - fresh)
        raise RuntimeError(
            f"only {n_score} tickers have the {week_close} close for the {snapshot_date(week)} "
            f"snapshot (recent weeks: ~{recent}); {len(stale)} stopped earlier that week, e.g. "
            f"{', '.join(stale[:20])}. Check the refresh step's failed fetches, then re-run."
        )

    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    labeled.to_parquet(TRAIN_PARQUET, index=False)
    score.to_parquet(SCORE_PARQUET, index=False)
    return {
        "rows": int(len(labeled)),
        "tickers": int(labeled["ticker"].nunique()),
        "first_week": snapshot_date(labeled["date"].min()),
        "last_week": snapshot_date(labeled["date"].max()),
        "score_snapshot": snapshot_date(week),
        "week_close": str(week_close),
        "score_tickers": n_score,
        "stale_tickers": sorted(set(closes) - fresh),
        "missing_tickers": sorted(set(labeled["ticker"]) - set(closes)),
    }


# ── Model ───────────────────────────────────────────────────────────────────


def training_frame(df: pd.DataFrame, target: str = TARGET,
                   features: list[str] = FEATURES) -> pd.DataFrame:
    """Rows the ranker can learn from: known target, every feature present,
    and a real cohort each week (MIN_COHORT tickers)."""
    md = df[~df["ticker"].isin(EXCLUDED)].dropna(subset=features + [target])
    sizes = md.groupby("date")["ticker"].transform("nunique")
    return md[sizes >= MIN_COHORT].reset_index(drop=True)


def fit_ranker(rows: pd.DataFrame, target: str = TARGET,
               features: list[str] = FEATURES) -> xgb.Booster:
    """One rank:ndcg fit; each week is a query group graded into quintiles
    of its realized return (grades come from training rows only)."""
    import numpy as np
    import pandas as pd
    import xgboost as xgb

    rows = rows.sort_values("date")
    grades = rows.groupby("date")[target].transform(
        lambda s: pd.qcut(s.rank(method="first"), N_GRADES, labels=False)).astype(int)
    dm = xgb.DMatrix(rows[features], label=grades)
    dm.set_group(np.bincount(rows["date"].astype("category").cat.codes.values))
    return xgb.train(PARAMS, dm, num_boost_round=N_ROUNDS)


def walk_forward(md: pd.DataFrame, target: str = TARGET, features: list[str] = FEATURES,
                 horizon_weeks: int = HORIZON_WEEKS, start: str = BACKTEST_START) -> pd.DataFrame:
    """Out-of-sample scores for every week since `start`.

    Refits once a quarter on rows whose outcome had closed by that quarter's
    first week (label + horizon_weeks <= cutoff), then ranks the next 13
    weekly cohorts with it: what a Friday run back then could have known.
    The live job refits every week, so it sees slightly more than this.
    Each score comes back next to its realized OUTCOME and `target`.
    """
    import pandas as pd
    import xgboost as xgb

    horizon = pd.Timedelta(weeks=horizon_weeks)
    quarter = pd.Timedelta(weeks=13)
    out = []
    for c in pd.date_range(start, md["date"].max(), freq="QS"):
        cutoff = c - pd.Timedelta(days=c.weekday())
        train = md[(md["date"] + horizon <= cutoff) & md[target].notna()]
        test = md[(md["date"] >= cutoff) & (md["date"] < cutoff + quarter)]
        if test.empty or train["date"].nunique() < 52:
            continue
        bst = fit_ranker(train, target, features)
        cols = ["date", "ticker"] + list(dict.fromkeys([OUTCOME, target]))
        out.append(test[cols].assign(pred=bst.predict(xgb.DMatrix(test[features]))))
    return pd.concat(out, ignore_index=True)


def weekly_results(scored: pd.DataFrame, bench: pd.Series,
                   outcome: str = OUTCOME) -> pd.DataFrame:
    """Per week: top-10 and whole-list equal-weight `outcome`, the
    benchmark's, the cross-sectional rank IC and precision@10."""
    import pandas as pd

    rows = []
    for d, g in scored.dropna(subset=[outcome]).groupby("date"):
        g = g.sort_values("pred", ascending=False)
        realized_top = g[outcome].rank(ascending=False, method="first") <= TOP_K
        rows.append({
            "date": d,
            "n": len(g),
            "top10": g[outcome].head(TOP_K).mean(),
            "universe": g[outcome].mean(),
            "spx": bench.get(d),
            "ic": g["pred"].corr(g[outcome], method="spearman"),
            "prec10": realized_top.head(TOP_K).mean(),
        })
    return pd.DataFrame(rows)


def validation_summary(weeks: pd.DataFrame) -> dict:
    """Headline walk-forward numbers. Weeks don't overlap (1-week outcome),
    so the plain t-stat over weeks is valid."""
    import numpy as np

    excess = weeks["top10"] - weeks["universe"]
    vs_spx = (weeks["top10"] - weeks["spx"]).dropna()
    return {
        "weeks": int(len(weeks)),
        "test_rows": int(weeks["n"].sum()),
        "rank_ic": float(weeks["ic"].mean()),
        "top10_excess": float(excess.mean()),
        "top10_t": float(excess.mean() / (excess.std(ddof=1) / np.sqrt(len(excess)))),
        "top10_hit": float((excess > 0).mean()),
        "top10_vs_spx": float(vs_spx.mean()) if len(vs_spx) else None,
        "top10_vs_spx_hit": float((vs_spx > 0).mean()) if len(vs_spx) else None,
        "precision10": float(weeks["prec10"].mean()),
        "precision10_random": float((TOP_K / weeks["n"]).mean()),
    }


def rank_cohort(bst: xgb.Booster, cohort: pd.DataFrame) -> pd.DataFrame:
    """Score this week's snapshot: rank 1 = most likely to lead next week."""
    import xgboost as xgb

    cohort = cohort[~cohort["ticker"].isin(EXCLUDED)].dropna(subset=FEATURES)
    ranked = cohort[["ticker", "sector"]].assign(
        score=bst.predict(xgb.DMatrix(cohort[FEATURES])))
    ranked = ranked.sort_values("score", ascending=False).reset_index(drop=True)
    ranked["rank"] = range(1, len(ranked) + 1)
    return ranked


# ── Export ──────────────────────────────────────────────────────────────────


def _clean(v):
    """NaN -> None for DuckDB parameters."""
    return None if v is None or v != v else float(v)


def export_weekly(
    warehouse: Warehouse,
    as_of: str,
    ranked: pd.DataFrame,
    weeks: pd.DataFrame,
    validation: dict,
    outcomes: pd.DataFrame,
    bench: pd.Series,
) -> dict:
    """Write this week's list, grade earlier lists, replace the backtest.

    `outcomes` is every labeled (ticker, week) row: a list published at
    as_of X is graded on the X-week row's OUTCOME (next Monday open to
    Friday close), which exists once that week has closed. Grading is
    incremental — only lists whose realized_return is still NULL.
    """
    import pandas as pd

    rows = [(as_of, int(r.rank), r.ticker, r.sector, round(float(r.score), 6))
            for r in ranked.itertuples()]
    backtest = [
        (snapshot_date(w.date), "backtest", _clean(w.top10), _clean(w.universe),
         _clean(w.spx), int(w.n))
        for w in weeks.itertuples()
    ]
    realized = outcomes.set_index(["date", "ticker"])[OUTCOME]
    graded = []

    with warehouse.connect() as con:
        con.execute("DELETE FROM mart.weekly_rankings WHERE as_of = ?", [as_of])
        con.executemany(
            "INSERT INTO mart.weekly_rankings (as_of, rank, ticker, sector, score)"
            " VALUES (?, ?, ?, ?, ?)", rows)

        pending = [d for (d,) in con.execute(
            "SELECT DISTINCT as_of FROM mart.weekly_rankings"
            " WHERE realized_return IS NULL AND as_of < ? ORDER BY as_of", [as_of]
        ).fetchall()]
        for d in pending:
            label = week_label(d)
            listed = con.execute(
                "SELECT ticker, rank FROM mart.weekly_rankings WHERE as_of = ?", [d]
            ).fetchall()
            values = {t: realized.get((label, t)) for t, _ in listed}
            if all(_clean(v) is None for v in values.values()):
                continue  # that week hasn't closed yet
            con.executemany(
                "UPDATE mart.weekly_rankings SET realized_return = ? WHERE as_of = ? AND ticker = ?",
                [(_clean(v), d, t) for t, v in values.items()])
            frame = pd.DataFrame(listed, columns=["ticker", "rank"]).assign(
                ret=[_clean(values[t]) for t, _ in listed]).dropna(subset=["ret"])
            con.execute("DELETE FROM mart.weekly_track_record WHERE week = ? AND source = 'live'", [d])
            con.execute(
                "INSERT INTO mart.weekly_track_record"
                " (week, source, top10_return, universe_return, spx_return, n_stocks)"
                " VALUES (?, 'live', ?, ?, ?, ?)",
                [d, float(frame[frame["rank"] <= TOP_K]["ret"].mean()),
                 float(frame["ret"].mean()), _clean(bench.get(label)), len(frame)])
            graded.append(str(d))

        con.execute("DELETE FROM mart.weekly_track_record WHERE source = 'backtest'")
        con.executemany(
            "INSERT INTO mart.weekly_track_record"
            " (week, source, top10_return, universe_return, spx_return, n_stocks)"
            " VALUES (?, ?, ?, ?, ?, ?)", backtest)

        v = {"run_at": pd.Timestamp.now(tz="UTC").tz_localize(None).to_pydatetime(),
             "as_of": as_of, "target": TARGET, **validation}
        con.execute(
            f"INSERT INTO mart.weekly_validation ({', '.join(v)})"
            f" VALUES ({', '.join('?' * len(v))})", list(v.values()))
    return {"ranked": len(rows), "backtest_weeks": len(backtest), "graded_lists": graded}


def train_and_rank() -> dict:
    """Walk-forward validate, refit on every closed week, rank this week's
    snapshot and export. Reads the parquets rebuild_weekly_dataset wrote."""
    import pandas as pd

    from .storage import Warehouse

    train = pd.read_parquet(TRAIN_PARQUET)
    cohort = pd.read_parquet(SCORE_PARQUET)
    bench = train[train["ticker"] == BENCHMARK].set_index("date")[OUTCOME]

    md = training_frame(train)
    weeks = weekly_results(walk_forward(md), bench)
    validation = validation_summary(weeks)

    bst = fit_ranker(md)
    ranked = rank_cohort(bst, cohort)
    as_of = snapshot_date(cohort["date"].iloc[0])
    validation |= {
        "train_rows": int(len(md)),
        "train_tickers": int(md["ticker"].nunique()),
        "train_first": snapshot_date(md["date"].min()),
        "train_last": snapshot_date(md["date"].max()),
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    bst.save_model(str(ARTIFACTS_DIR / f"{MODEL_NAME}.json"))
    meta = {"model": MODEL_NAME, "objective": PARAMS["objective"], "target": TARGET,
            "features": FEATURES, "excluded": sorted(EXCLUDED), "n_rounds": N_ROUNDS,
            "params": PARAMS, "as_of": as_of, **validation}
    (ARTIFACTS_DIR / f"{MODEL_NAME}.meta.json").write_text(json.dumps(meta, indent=2))

    warehouse = Warehouse()
    warehouse.init_schema()
    exported = export_weekly(warehouse, as_of, ranked, weeks, validation, train, bench)
    return {"as_of": as_of, "top10": ranked["ticker"].head(TOP_K).tolist(),
            **validation, **exported}
