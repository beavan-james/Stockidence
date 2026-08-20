from __future__ import annotations

import duckdb
import pytest

from stockidence_app.service import market


@pytest.fixture(autouse=True)
def _reset_db_path_cache():
    market._PATH = None
    yield
    market._PATH = None


def _build_db(tmp_path) -> str:
    db = tmp_path / "market.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA raw")
    con.execute(
        "CREATE TABLE raw.raw_commodities (nominal VARCHAR, date DATE, payload JSON)"
    )
    con.executemany(
        "INSERT INTO raw.raw_commodities VALUES (?, ?, ?)",
        [
            ("GOLD", "2026-08-19", '{"date": "2026-08-19", "price": "4341.8343555459"}'),
            ("SILVER", "2026-08-19", '{"date": "2026-08-19", "value": "62.9885200651"}'),
            ("GOLD", "2026-07-31", '{"date": "2026-07-31", "value": "4101.40"}'),
        ],
    )
    con.execute(
        "CREATE TABLE raw.raw_gainers_losers "
        "(ticker VARCHAR, date DATE, payload JSON)"
    )
    con.executemany(
        "INSERT INTO raw.raw_gainers_losers VALUES (?, ?, ?)",
        [
            ("NVDA", "2026-08-19",
             '{"bucket": "top_gainers", "price": "152.44", "change_amount": "2.883333", '
             '"change_percentage": "2.193336128761737%", "volume": "182342345"}'),
            ("WETO", "2026-08-19",
             '{"bucket": "top_gainers", "price": "8.22", "change_amount": "4.61", '
             '"change_percentage": "127.70%", "volume": "58226265"}'),
        ],
    )
    con.execute(
        "CREATE TABLE raw.raw_company_profile (ticker VARCHAR, payload JSON)"
    )
    con.execute(
        "INSERT INTO raw.raw_company_profile VALUES (?, ?)",
        ["MSFT", '{"name": "Microsoft Corp", "logo": "https://static2.finnhub.io/file/publicdatany/finnhubimage/stock_logo/MSFT.png"}'],
    )
    con.close()
    return str(db)


def test_get_commodities_reads_price_or_value(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_db(tmp_path))
    out = {c["nominal"]: c for c in market.get_commodities()}
    assert out["GOLD"]["price"] == 4341.83
    assert out["SILVER"]["price"] == 62.99


def test_mover_change_display_rounded(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_db(tmp_path))
    movers = market.get_market_movers()
    nvda = next(r for r in movers["top_gainers"] if r["ticker"] == "NVDA")
    assert nvda["change_display"] == "+2.88 (+2.19%)"


def test_get_company_logo(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_db(tmp_path))
    assert market.get_company_logo("msft") == (
        "https://static2.finnhub.io/file/publicdatany/finnhubimage/stock_logo/MSFT.png"
    )
    assert market.get_company_logo("NOPE") == ""