"""Overwrite guard + SEC EDGAR balance-sheet backfill."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from stockidence.ingest.endpoints import Provider
from stockidence.ingest.engine import IngestEngine
from stockidence.ingest.raw_mapping import keep_filled_report_sections, normalize_sec_balance_sheets
from stockidence.ingest.staleness import StalenessGate
from stockidence.staging.staging import balance_sheet_sources, rebuild_financials_reported
from stockidence.storage import Warehouse

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

BS = [{"concept": "us-gaap_Assets", "unit": "usd", "label": "Total assets", "value": 100.0}]
IC = [{"concept": "us-gaap_NetIncomeLoss", "unit": "usd", "label": "Net income", "value": 5.0}]


def filing(accn, year, quarter, filed, end, bs):
    return {
        "accessNumber": accn, "symbol": "DKNG", "cik": "1883685", "year": year, "quarter": quarter,
        "form": "10-Q", "filedDate": f"{filed} 00:00:00", "endDate": f"{end} 00:00:00",
        "report": {"bs": bs, "ic": IC, "cf": []},
    }


Q1 = filing("0001883685-26-000010", 2026, 1, "2026-05-08", "2026-03-31", BS)
Q2_EMPTY = filing("0001883685-26-000020", 2026, 2, "2026-08-07", "2026-06-30", [])

COMPANY_FACTS = {
    "cik": 1883685,
    "facts": {
        "us-gaap": {
            "Assets": {"label": "Assets", "units": {"USD": [
                # Q2 10-Q: current column + the year-end comparative
                {"end": "2026-06-30", "val": 120, "accn": "0001883685-26-000020", "form": "10-Q", "filed": "2026-08-07"},
                {"end": "2025-12-31", "val": 90, "accn": "0001883685-26-000020", "form": "10-Q", "filed": "2026-08-07"},
                {"end": "2026-03-31", "val": 100, "accn": "0001883685-26-000010", "form": "10-Q", "filed": "2026-05-08"},
                # outside the lookback
                {"end": "2020-06-30", "val": 10, "accn": "0001883685-20-000020", "form": "10-Q", "filed": "2020-08-07"},
            ]}},
            "StockholdersEquity": {"label": "Equity", "units": {"USD": [
                {"end": "2026-06-30", "val": 60, "accn": "0001883685-26-000020", "form": "10-Q", "filed": "2026-08-07"},
                {"end": "2025-12-31", "val": 50, "accn": "0001883685-26-000020", "form": "10-Q", "filed": "2026-08-07"},
            ]}},
            # a flow: has a start, so it's not balance sheet
            "NetIncomeLoss": {"label": "NI", "units": {"USD": [
                {"start": "2026-04-01", "end": "2026-06-30", "val": 7, "accn": "0001883685-26-000020",
                 "form": "10-Q", "filed": "2026-08-07"},
            ]}},
            # share counts aren't USD
            "CommonStockSharesOutstanding": {"label": "Shares", "units": {"shares": [
                {"end": "2026-06-30", "val": 500, "accn": "0001883685-26-000020", "form": "10-Q", "filed": "2026-08-07"},
            ]}},
        }
    },
}


class FakeFinnhub:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def financials_reported(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeSec:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def company_facts(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.fixture
def setup(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    fh = FakeFinnhub({"symbol": "DKNG", "data": [Q1]})
    sec = FakeSec(COMPANY_FACTS)
    return wh, IngestEngine(wh, clients={Provider.FINNHUB: fh, Provider.SEC_EDGAR: sec}), fh, sec


def _stored(wh, quarter):
    with wh.connect(read_only=True) as con:
        return json.loads(con.execute(
            "SELECT payload FROM raw.raw_financials_reported WHERE ticker = 'DKNG' AND quarter = ?",
            [quarter]).fetchone()[0])


# --- guard ---

def test_guard_keeps_stored_section_for_same_filing():
    incoming = filing(Q1["accessNumber"], 2026, 1, "2026-05-08", "2026-03-31", [])
    merged = keep_filled_report_sections(incoming, Q1)
    assert merged["report"]["bs"] == BS
    assert merged["report"]["ic"] == IC
    assert merged["_kept_sections"] == ["bs"]


def test_guard_lets_an_amendment_through():
    amended = filing("0001883685-26-000099", 2026, 1, "2026-06-01", "2026-03-31", [])
    assert keep_filled_report_sections(amended, Q1) is amended


def test_guard_is_a_no_op_when_nothing_was_emptied():
    assert keep_filled_report_sections(Q1, Q1) is Q1


def test_refetch_with_empty_balance_sheet_keeps_the_stored_one(setup):
    wh, eng, fh, _ = setup
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)
    fh.response = {"symbol": "DKNG", "data": [
        filing(Q1["accessNumber"], 2026, 1, "2026-05-08", "2026-03-31", [])]}
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW + timedelta(days=1), force=True)
    stored = _stored(wh, 1)
    assert stored["report"]["bs"] == BS
    assert stored["_kept_sections"] == ["bs"]


# --- SEC normalizer ---

def test_sec_normalizer_keeps_each_filings_own_balance_sheet_date():
    rows = normalize_sec_balance_sheets(COMPANY_FACTS, "DKNG", NOW)["raw_sec_balance_sheets"]
    by_accn = {r["accession_number"]: r["payload"] for r in rows}
    assert set(by_accn) == {"0001883685-26-000020", "0001883685-26-000010"}  # 2020 filing is past the lookback
    q2 = by_accn["0001883685-26-000020"]
    assert q2["endDate"] == "2026-06-30"
    assert {d["concept"]: d["value"] for d in q2["bs"]} == {
        "us-gaap_Assets": 120, "us-gaap_StockholdersEquity": 60}


# --- gap check ---

def test_no_sec_call_when_finnhub_filings_are_complete(setup):
    wh, eng, _, sec = setup
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)
    result = eng.ingest_on_demand("sec_balance_sheets", "DKNG", now=NOW)
    assert not result.fetched and sec.calls == []


def test_sec_fills_a_gap_once(setup):
    wh, eng, fh, sec = setup
    fh.response = {"symbol": "DKNG", "data": [Q1, Q2_EMPTY]}
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)

    first = eng.ingest_on_demand("sec_balance_sheets", "DKNG", now=NOW + timedelta(minutes=1))
    assert first.fetched and sec.calls == [{"cik": "1883685"}]

    second = eng.ingest_on_demand("sec_balance_sheets", "DKNG", now=NOW + timedelta(minutes=2))
    assert not second.fetched


def test_gap_sec_doesnt_have_waits_for_the_next_finnhub_delivery(setup):
    wh, eng, fh, sec = setup
    missing = filing("0001883685-26-000030", 2026, 3, "2026-10-30", "2026-09-30", [])
    fh.response = {"symbol": "DKNG", "data": [Q1, Q2_EMPTY, missing]}
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)
    eng.ingest_on_demand("sec_balance_sheets", "DKNG", now=NOW + timedelta(minutes=1))

    gate = StalenessGate(wh)
    assert not gate.should_fetch("sec_balance_sheets", "DKNG", now=NOW + timedelta(minutes=2)).should_fetch

    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW + timedelta(days=7), force=True)
    assert gate.should_fetch("sec_balance_sheets", "DKNG", now=NOW + timedelta(days=7, minutes=1)).should_fetch


# --- staging merge ---

def test_staging_fills_empty_balance_sheet_from_sec(setup):
    wh, eng, fh, _ = setup
    fh.response = {"symbol": "DKNG", "data": [Q1, Q2_EMPTY]}
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)
    eng.ingest_on_demand("sec_balance_sheets", "DKNG", now=NOW + timedelta(minutes=1))

    assert rebuild_financials_reported(wh, "DKNG") == 2
    with wh.connect(read_only=True) as con:
        rows = {r[0]: (r[1], json.loads(r[2])) for r in con.execute(
            "SELECT quarter, bs_source, payload FROM staging.stg_financials_reported").fetchall()}
    q1_source, q1 = rows[1]
    q2_source, q2 = rows[2]
    assert q1_source == "finnhub" and q1["report"]["bs"] == BS
    assert q2_source == "sec"
    assert {d["concept"]: d["value"] for d in q2["report"]["bs"]} == {
        "us-gaap_Assets": 120, "us-gaap_StockholdersEquity": 60}
    assert q2["report"]["ic"] == IC  # Finnhub's other statements untouched
    assert balance_sheet_sources(wh, "2026-01-01") == {"finnhub": 1, "sec": 1}


def test_staging_marks_filings_neither_source_has(setup):
    wh, eng, fh, _ = setup
    fh.response = {"symbol": "DKNG", "data": [Q2_EMPTY]}
    eng.ingest_on_demand("financials_reported", "DKNG", now=NOW, force=True)
    rebuild_financials_reported(wh)
    assert balance_sheet_sources(wh, "2026-01-01") == {"none": 1}
