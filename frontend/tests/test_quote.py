from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest

from stockidence.service import market


@pytest.fixture(autouse=True)
def _reset_db_path_cache():
    market._PATH = None
    yield
    market._PATH = None


def _build_quote_db(tmp_path) -> str:
    db = tmp_path / "quote.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.raw_quotes (ticker VARCHAR, payload JSON)")
    con.execute("CREATE TABLE raw.raw_macro_indicators (indicator VARCHAR, date DATE, payload JSON)")
    con.execute("CREATE TABLE raw.raw_commodities (nominal VARCHAR, date DATE, payload JSON)")
    con.execute(
        "INSERT INTO raw.raw_quotes VALUES "
        "(?, ?)",
        [
            "AAPL",
            {
                "c": 261.74,
                "h": 263.31,
                "l": 260.5,
                "o": 260.9,
                "pc": 259.45,
                "t": int(datetime(2026, 8, 18, 20, 0, tzinfo=timezone.utc).timestamp()),
            },
        ],
    )
    con.close()
    return str(db)


def test_get_quote_reads_latest_raw_row(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_quote_db(tmp_path))
    quote = market.get_quote("aapl")
    assert quote is not None
    assert quote["price"] == 261.74
    assert quote["high"] == 263.31
    assert quote["prev_close"] == 259.45
    assert quote["as_of"] is not None


def test_get_quote_none_when_unknown_ticker(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_quote_db(tmp_path))
    assert market.get_quote("NOPE") is None


def test_get_quote_none_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "nope.duckdb"))
    assert market.get_quote("AAPL") is None