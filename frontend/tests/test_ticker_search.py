from __future__ import annotations

import duckdb
import pytest

from stockidence.service import warehouse


def _build_symbols_db(tmp_path) -> str:
    db = tmp_path / "symbols.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA raw")
    con.execute("CREATE TABLE raw.raw_stock_symbols (mic VARCHAR, symbol VARCHAR, payload JSON)")
    con.executemany(
        "INSERT INTO raw.raw_stock_symbols VALUES (?, ?, ?)",
        [
            ("XNAS", "AAPL", '{"description": "Apple Inc", "type": "Common Stock"}'),
            ("XNAS", "MSFT", '{"description": "Microsoft Corp", "type": "Common Stock"}'),
            ("XNYS", "GME", '{"description": "GameStop Corp", "type": "Common Stock"}'),
            ("XNYS", "BAC", '{"description": "Bank of America Corp", "type": "Common Stock"}'),
            ("ARCX", "TSLA", '{"description": "Tesla Inc", "type": "Common Stock"}'),
            ("XNSE", "TCS", '{"description": "Tata Consultancy Services", "type": "Common Stock"}'),
            ("XNAS", "AAPL.PREF", '{"description": "Apple Preferred", "type": "Preferred Stock"}'),
        ],
    )
    con.close()
    return str(db)


def test_search_tickers_prefix_matches_symbol(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_symbols_db(tmp_path))
    hits = warehouse.search_tickers("aapl")
    assert [h["symbol"] for h in hits] == ["AAPL", "AAPL.PREF"]
    assert hits[0]["description"] == "Apple Inc"


def test_search_tickers_substring_matches_description(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_symbols_db(tmp_path))
    hits = warehouse.search_tickers("microsoft")
    assert [h["symbol"] for h in hits] == ["MSFT"]


def test_search_tickers_excludes_non_us_exchanges(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_symbols_db(tmp_path))
    hits = warehouse.search_tickers("tata")
    assert hits == []


def test_search_tickers_empty_query_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", _build_symbols_db(tmp_path))
    assert warehouse.search_tickers("") == []


def test_search_tickers_graceful_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "nope.duckdb"))
    assert warehouse.search_tickers("aapl") == []