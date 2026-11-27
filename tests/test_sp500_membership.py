"""S&P 500 membership: the list's ingestion, its rename resolution in
staging, the dataset's point-in-time flag, and the model filters on it.

No network: the client runs on a mocked transport and the engine on a fake
client; the warehouse is a temporary DuckDB file."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from stockidence.ingest.clients.base import InvalidResponseError
from stockidence.ingest.clients.sp500_history import Sp500HistoryClient
from stockidence.ingest.endpoints import Provider
from stockidence.ingest.engine import IngestEngine
from stockidence.staging.sp500_membership import rebuild_sp500_membership
from stockidence.storage import Warehouse

NOW = datetime(2026, 12, 1, 2, 0, tzinfo=UTC)

CSV = """ticker,start_date,end_date
AAPL,1996-01-02,
MMC,1996-01-02,2026-01-14
MRSH,2026-01-14,
IR,1996-01-02,2009-07-01
IR,2010-11-17,
TT,2020-03-03,
CAG,1996-01-02,2026-06-30
BF.B,1996-01-02,
FISV,2001-04-02,2023-06-07
FI,2023-06-07,2025-11-11
FISV,2025-11-11,
"""


def _rows(text: str) -> list[dict[str, str]]:
    from stockidence.ingest.clients.sp500_history import parse_membership_csv

    return parse_membership_csv(text)


class FakeSp500History:
    def __init__(self, text: str = CSV):
        self.text = text

    def membership(self) -> list[dict[str, str]]:
        return _rows(self.text)


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "test.duckdb")
    wh.init_schema()
    return wh


def _land(wh: Warehouse, text: str = CSV, now: datetime = NOW) -> IngestEngine:
    engine = IngestEngine(wh, clients={Provider.SP500_HISTORY: FakeSp500History(text)})
    engine.ingest_scheduled("sp500_membership", now=now)
    return engine


def _spells(wh: Warehouse, ticker: str) -> list[tuple]:
    with wh.connect(read_only=True) as con:
        return con.execute(
            "SELECT listed_ticker, CAST(start_date AS VARCHAR), CAST(end_date AS VARCHAR)"
            " FROM staging.stg_sp500_membership WHERE ticker = ? ORDER BY start_date",
            [ticker],
        ).fetchall()


# ── client ──────────────────────────────────────────────────────────────────


def _client(monkeypatch, body: str, status: int = 200) -> Sp500HistoryClient:
    def fake_request(method, url, **kwargs):
        assert url.endswith("/sp500_ticker_start_end.csv")
        return httpx.Response(status, text=body, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    return Sp500HistoryClient(retries=0)


def test_client_reads_the_csv(monkeypatch):
    rows = _client(monkeypatch, CSV).membership()
    assert rows[0] == {"ticker": "AAPL", "start_date": "1996-01-02", "end_date": ""}
    assert rows[1]["end_date"] == "2026-01-14"
    assert len(rows) == 11


def test_client_refuses_a_page_that_is_not_the_list(monkeypatch):
    with pytest.raises(InvalidResponseError):
        _client(monkeypatch, "<html><body>moved</body></html>").membership()
    with pytest.raises(InvalidResponseError):
        _client(monkeypatch, "ticker,start_date,end_date\n").membership()


# ── raw + staging ───────────────────────────────────────────────────────────


def test_landing_keys_spells_and_bumps_one_watermark(warehouse):
    _land(warehouse)
    with warehouse.connect(read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM raw.raw_sp500_membership").fetchone()[0] == 11
        watermarks = con.execute(
            "SELECT dimension_key FROM control.watermarks WHERE endpoint = 'raw.raw_sp500_membership'"
        ).fetchall()
    assert watermarks == [("SP500",)]


def test_staging_gives_a_renamed_company_its_old_tickers_spells(warehouse):
    _land(warehouse)
    rebuild_sp500_membership(warehouse)
    assert _spells(warehouse, "MRSH") == [
        ("MMC", "1996-01-02", "2026-01-14"),
        ("MRSH", "2026-01-14", None),
    ]
    assert _spells(warehouse, "MMC") == []
    # Fiserv: FISV, then FI for two years, then FISV again
    assert [s[0] for s in _spells(warehouse, "FISV")] == ["FISV", "FI", "FISV"]


def test_staging_splits_a_ticker_that_changed_companies(warehouse):
    _land(warehouse)
    rebuild_sp500_membership(warehouse)
    # IR was Trane Technologies' ticker until 2020-03-03, Ingersoll Rand's after
    assert _spells(warehouse, "TT") == [
        ("IR", "1996-01-02", "2009-07-01"),
        ("IR", "2010-11-17", "2020-03-03"),
        ("TT", "2020-03-03", None),
    ]
    assert _spells(warehouse, "IR") == [("IR", "2020-03-03", None)]


def test_staging_reads_only_the_latest_fetch(warehouse):
    _land(warehouse)
    corrected = CSV.replace("CAG,1996-01-02,2026-06-30\n", "")
    _land(warehouse, corrected, now=datetime(2027, 1, 1, 2, 0, tzinfo=UTC))
    rebuild_sp500_membership(warehouse)
    assert _spells(warehouse, "CAG") == []
    assert _spells(warehouse, "AAPL") == [("AAPL", "1996-01-02", None)]


# ── dataset flag ────────────────────────────────────────────────────────────


@pytest.fixture
def membership(warehouse):
    from stockidence.weekly import _build_dataset_module

    _land(warehouse)
    rebuild_sp500_membership(warehouse)
    bd = _build_dataset_module()
    return bd, bd._load_sp500_membership(warehouse)


def _flags(bd, membership, rows):
    frame = pd.DataFrame(rows, columns=["ticker", "asof"])
    frame["asof"] = pd.to_datetime(frame["asof"])
    return pd.concat([frame, bd._index_membership(frame, membership)], axis=1)


def test_in_index_is_point_in_time(membership):
    bd, m = membership
    out = _flags(
        bd,
        m,
        [
            ("CAG", "2025-12-31"),  # still a member
            ("CAG", "2026-06-30"),  # out from 2026-06-30
            ("IR", "2019-12-31"),  # Ingersoll Rand before it had the IR line
            ("IR", "2020-03-31"),
            ("TT", "2019-12-31"),  # Trane's spell, listed under IR back then
            ("MRSH", "2020-06-30"),  # Marsh McLennan's MMC years
        ],
    )
    assert out["in_index"].tolist() == [True, False, False, True, True, True]


def test_status_says_where_each_ticker_stands_today(membership):
    bd, m = membership
    out = _flags(
        bd,
        m,
        [
            ("AAPL", "2026-09-30"),
            ("CAG", "2026-09-30"),
            ("SHOP", "2026-09-30"),
            ("MMC", "2026-09-30"),
            ("MRSH", "2026-09-30"),
            ("FI", "2024-06-28"),
            ("FISV", "2024-06-28"),
            ("BF-B", "2026-09-30"),
        ],
    ).set_index("ticker")
    assert out["sp500_status"].to_dict() == {
        "AAPL": "current",
        "CAG": "former",
        "SHOP": "never",
        "MMC": "duplicate",  # MRSH carries the same history
        "MRSH": "current",
        "FI": "duplicate",
        "FISV": "current",
        "BF-B": "current",  # the list spells it BF.B
    }
    # a duplicate never counts, even on days the company was in the index
    assert not out.loc["MMC", "in_index"]
    assert not out.loc["FI", "in_index"]
    assert out.loc["FISV", "in_index"]


def test_a_renamed_ticker_alone_in_the_warehouse_stands_for_its_company(membership):
    bd, m = membership
    out = _flags(bd, m, [("MMC", "2020-06-30")])
    assert out["sp500_status"].tolist() == ["current"]
    assert out["in_index"].tolist() == [True]


def test_no_list_yet_counts_every_row(membership):
    bd, m = membership
    out = _flags(bd, m.iloc[0:0], [("SHOP", "2020-06-30"), ("CAG", "2026-09-30")])
    assert out["in_index"].all()
    assert set(out["sp500_status"]) == {"unknown"}


# ── model filters ───────────────────────────────────────────────────────────


def _cohort(n: int = 25) -> pd.DataFrame:
    from stockidence.weekly import FEATURES, TARGET

    rows = [
        {
            "date": pd.Timestamp("2025-06-02"),
            "ticker": f"T{i:02d}",
            "sector": "Tech",
            TARGET: 0.01 * i,
            **dict.fromkeys(FEATURES, 1.0),
            "in_index": True,
            "sp500_status": "current",
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_weekly_training_keeps_only_rows_in_the_index():
    from stockidence.weekly import training_frame

    df = _cohort()
    df.loc[0, ["in_index", "sp500_status"]] = [False, "former"]
    df.loc[1, ["in_index", "sp500_status"]] = [False, "current"]  # joined later
    assert set(training_frame(df)["ticker"]) == {f"T{i:02d}" for i in range(2, 25)}
    # a parquet built before the flag existed trains on every row
    assert len(training_frame(df.drop(columns=["in_index"]))) == 25


def test_weekly_list_drops_former_members_and_duplicates():
    from stockidence.weekly import _rankable

    df = _cohort(4)
    df["sp500_status"] = ["current", "never", "former", "duplicate"]
    assert _rankable(df)["ticker"].tolist() == ["T00", "T01"]


# ── orchestration ───────────────────────────────────────────────────────────


def _step_order(job) -> list[str]:
    from dagster._core.execution.api import create_execution_plan

    return [s.key for s in create_execution_plan(job).get_steps_to_execute_in_topo_order()]


def test_cadence_rebuilds_run_after_the_ingest():
    from stockidence.definitions import daily_job, monthly_job

    assert _step_order(monthly_job) == ["ingest_monthly_op", "monthly_sp500_membership_op"]
    assert _step_order(daily_job) == [
        "ingest_daily_op",
        "daily_fred_staging_op",
        "daily_fred_mart_op",
    ]
