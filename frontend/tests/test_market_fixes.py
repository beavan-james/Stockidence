from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb
import pytest

from stockidence_app.service import market

_TODAY = date.today()


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
    con.execute(
        "CREATE TABLE raw.raw_ipo_calendar (symbol VARCHAR, date DATE, payload JSON)"
    )
    con.executemany(
        "INSERT INTO raw.raw_ipo_calendar VALUES (?, ?, ?)",
        [
            ("AAA", "2026-08-04", '{"date": "2026-08-04", "symbol": "AAA", "name": "Old Co", "status": "priced"}'),
            ("LYNX", "2026-08-19", '{"date": "2026-08-19", "symbol": "LYNX", "name": "Lyntris Inc.", "status": "expected", "price": "17.50"}'),
            ("PTT", "2026-09-08", '{"date": "2026-09-08", "symbol": "PTT", "name": "SIYATA PTT", "status": "expected"}'),
        ],
    )
    con.execute(
        "CREATE TABLE raw.raw_earnings_calendar (symbol VARCHAR, quarter INTEGER, year INTEGER, payload JSON)"
    )
    def _earn(symbol: str, d: date, hour: str, eps: float) -> tuple:
        ds = d.isoformat()
        return (
            symbol,
            3,
            2026,
            json.dumps(
                {
                    "date": ds,
                    "symbol": symbol,
                    "quarter": 3,
                    "year": 2026,
                    "hour": hour,
                    "epsEstimate": eps,
                }
            ),
        )

    con.executemany(
        "INSERT INTO raw.raw_earnings_calendar VALUES (?, ?, ?, ?)",
        [
            _earn("AARD", _TODAY, "amc", -0.8917),
            _earn("ADI", _TODAY, "bmo", 3.3681),
            _earn("ZYX", _TODAY + timedelta(days=43), "bmo", 1.25),
            _earn("ZZZ", _TODAY + timedelta(days=100), "amc", 0.5),
        ],
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


def test_ipo_calendar_limit_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_db(tmp_path))
    all_ipos = market.get_ipo_calendar(limit=10)
    assert [i["symbol"] for i in all_ipos] == ["LYNX", "PTT"]
    assert market.get_ipo_calendar(limit=1) == all_ipos[:1]


def test_earnings_calendar_limit_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_db(tmp_path))
    all_rows = market.get_earnings_calendar(limit=10)
    assert [e["symbol"] for e in all_rows] == ["AARD", "ADI", "ZYX", "ZZZ"]
    assert market.get_earnings_calendar(limit=2) == all_rows[:2]