"""Daily movers: latest snapshot only, ranked lists, bucket in the raw key."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from stockidence.ingest.raw_mapping import normalize_for
from stockidence.service import market
from stockidence.storage import Warehouse

NOW = datetime(2026, 10, 2, 21, 30, tzinfo=timezone.utc)


def _mover(ticker, price, change_amount, change_percentage, volume):
    return {"ticker": ticker, "price": str(price), "change_amount": str(change_amount),
            "change_percentage": change_percentage, "volume": str(volume)}


def _land(wh, payload, now):
    rows = normalize_for("top_gainers_losers", payload, "top_gainers_losers", now)["raw_gainers_losers"]
    wh.land("raw_gainers_losers", rows, fetched_at=now)


def _warehouse(tmp_path, monkeypatch):
    wh = Warehouse(tmp_path / "w.duckdb")
    wh.init_schema()
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "w.duckdb"))
    return wh


def test_ticker_in_two_lists_keeps_both_rows(tmp_path, monkeypatch):
    wh = _warehouse(tmp_path, monkeypatch)
    hot = _mover("HOT", 35.0, 13.7, "63.8%", 23_762_493)
    _land(wh, {"top_gainers": [hot], "most_actively_traded": [hot]}, NOW)

    with wh.connect(read_only=True) as con:
        buckets = con.execute(
            "SELECT bucket FROM raw.raw_gainers_losers WHERE ticker = 'HOT' ORDER BY bucket"
        ).fetchall()
    assert buckets == [("most_actively_traded",), ("top_gainers",)]


def test_movers_rank_by_dollar_move_and_dollar_volume(tmp_path, monkeypatch):
    wh = _warehouse(tmp_path, monkeypatch)
    _land(wh, {
        "top_gainers": [
            _mover("PENNY", 0.18, 0.046, "34.0%", 1_532),          # big %, no money
            _mover("REAL", 35.11, 13.68, "63.8%", 23_762_493),
            _mover("MID", 12.0, 2.0, "20.0%", 5_000_000),
        ],
        "top_losers": [
            _mover("TINY", 0.05, -0.02, "-34.0%", 68),
            _mover("DROP", 3.75, -1.59, "-29.8%", 274_890),
            _mover("BIGDROP", 80.0, -12.0, "-13.0%", 9_000_000),
        ],
        "most_actively_traded": [
            _mover("SUB1", 0.12, -0.01, "-5.9%", 55_825_585),      # most shares, few dollars
            _mover("CORO", 37.25, 0.12, "0.3%", 130_910_852),
            _mover("FTFT", 8.04, 5.16, "179.2%", 120_655_637),
        ],
    }, NOW)

    m = market.get_market_movers()

    assert [r["ticker"] for r in m["top_gainers"]] == ["REAL", "MID", "PENNY"]
    assert [r["ticker"] for r in m["top_losers"]] == ["BIGDROP", "DROP", "TINY"]
    assert [r["ticker"] for r in m["most_actively_traded"]] == ["CORO", "FTFT", "SUB1"]


def test_movers_use_latest_day_only_and_cap_at_limit(tmp_path, monkeypatch):
    wh = _warehouse(tmp_path, monkeypatch)
    old = datetime(2026, 9, 3, 21, 30, tzinfo=timezone.utc)
    _land(wh, {"top_gainers": [_mover("STALE", 50.0, 20.0, "66%", 90_000_000)]}, old)
    fresh = [_mover(f"T{i:02d}", 10.0, 1.0 + i, "10%", 1_000_000) for i in range(15)]
    _land(wh, {"top_gainers": fresh}, NOW)

    m = market.get_market_movers()

    tickers = [r["ticker"] for r in m["top_gainers"]]
    assert "STALE" not in tickers
    assert len(tickers) == market.MOVERS_LIMIT == 10
    assert tickers[0] == "T14"  # largest dollar change x volume
    assert m["movers_as_of"] == "Oct 02, 2026"


def test_init_schema_migrates_old_table_keeping_rows(tmp_path):
    """Warehouses created before bucket joined the key are rebuilt in place."""
    path = tmp_path / "old.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA raw")
    con.execute(
        """
        CREATE TABLE raw.raw_gainers_losers (
            ticker VARCHAR, date DATE, payload JSON NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (ticker, date)
        )
        """
    )
    con.execute(
        "INSERT INTO raw.raw_gainers_losers VALUES"
        " ('AAA', '2026-10-02', '{\"bucket\": \"top_losers\", \"price\": \"1\"}', now())"
    )
    con.close()

    wh = Warehouse(path)
    wh.init_schema()
    wh.init_schema()  # idempotent

    with wh.connect(read_only=True) as con:
        rows = con.execute("SELECT ticker, date, bucket FROM raw.raw_gainers_losers").fetchall()
    assert rows == [("AAA", date(2026, 10, 2), "top_losers")]
