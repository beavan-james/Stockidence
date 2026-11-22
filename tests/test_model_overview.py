"""GET /api/model/overview: the persisted walk-forward validation metrics.

The retrain notebook appends one mart.model_validation row per run; the
overview serves the newest and must degrade to None before the first run
that records it.
"""

from __future__ import annotations

from stockidence.service import ranking
from stockidence.storage import Warehouse

_COLS = (
    "run_at, as_of, quarters, test_rows, rank_ic, top10_excess, top10_t, top10_hit,"
    " top25_excess, top25_t, top25_hit, topq_excess, topq_t, topq_hit,"
    " precision10, precision10_random, precision25, precision25_random,"
    " train_rows, train_tickers, train_first, train_last"
)


def _warehouse(tmp_path, monkeypatch):
    wh = Warehouse(tmp_path / "w.duckdb")
    wh.init_schema()
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "w.duckdb"))
    return wh


def _insert(wh, run_at, rank_ic, train_rows):
    with wh.connect() as con:
        con.execute(
            f"INSERT INTO mart.model_validation ({_COLS}) VALUES"
            " (?, '2026-09-30', 26, 7691, ?, 0.0425, 1.51, 0.62, 0.0413, 1.91, 0.62,"
            " 0.0262, 1.82, 0.62, 0.146, 0.034, 0.218, 0.085, ?, 380,"
            " '2012-09-30', '2026-06-30')",
            [run_at, rank_ic, train_rows],
        )


def test_overview_serves_latest_validation_run(tmp_path, monkeypatch):
    wh = _warehouse(tmp_path, monkeypatch)
    _insert(wh, "2026-07-01 03:30:00", 0.1634, 15874)
    _insert(wh, "2026-10-03 23:53:00", 0.1424, 15916)

    v = ranking.get_model_overview()["validation"]

    assert v["rank_ic"] == 0.1424
    assert v["train_rows"] == 15916
    assert v["train_tickers"] == 380
    assert v["test_rows"] == 7691
    assert v["precision10_random"] == 0.034
    # Dates are JSON-ready strings, like the rest of the overview.
    assert v["as_of"] == "2026-09-30"
    assert v["train_first"] == "2012-09-30"
    assert v["run_at"].startswith("2026-10-03T23:53")


def test_overview_validation_is_none_before_first_recorded_run(tmp_path, monkeypatch):
    _warehouse(tmp_path, monkeypatch)

    overview = ranking.get_model_overview()

    assert overview["validation"] is None
    assert overview["track_record"] == []
