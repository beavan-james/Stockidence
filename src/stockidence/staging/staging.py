"""Staging rebuild: raw → typed, cleaned, deduped bars (staging layer).

Staging cleans, mart aggregates. This module holds the one staging table:
stg_prices_daily — typing/cleaning/dedup plus grain-preserving transforms
(return_1d). Everything that aggregates over bars lives in mart.mart.

Pure derivation, no API calls (registry cadence DERIVED). The rebuild is a
full per-ticker recompute: delete the ticker's staging rows, rebuild from
raw JSON payloads. Idempotent by construction, and immune to Twelve Data's
occasional historical-bar revisions (a backfill or split adjustment simply
flows through next run).
"""

from __future__ import annotations

from ..storage import Warehouse


def rebuild_prices_daily(warehouse: Warehouse, ticker: str) -> int:
    """Typed daily bars with 1-day simple returns. Rows whose payload lacks a
    valid O/H/L/C (holes in the API feed) don't make it to staging."""
    with warehouse.connect() as con:
        con.execute("DELETE FROM staging.stg_prices_daily WHERE ticker = ?", [ticker])
        con.execute(
            """
            INSERT INTO staging.stg_prices_daily
                (ticker, date, open, high, low, close, volume, return_1d)
            SELECT
                ticker,
                date,
                CAST(json_extract_string(payload, '$.open')  AS DOUBLE),
                CAST(json_extract_string(payload, '$.high')  AS DOUBLE),
                CAST(json_extract_string(payload, '$.low')   AS DOUBLE),
                CAST(json_extract_string(payload, '$.close') AS DOUBLE),
                GREATEST(CAST(json_extract_string(payload, '$.volume') AS DOUBLE), 0),
                CAST(json_extract_string(payload, '$.close') AS DOUBLE) /
                    LAG(CAST(json_extract_string(payload, '$.close') AS DOUBLE))
                        OVER (PARTITION BY ticker ORDER BY date) - 1
            FROM raw.raw_prices_daily
            WHERE ticker = ?
              AND json_extract_string(payload, '$.open')  IS NOT NULL
              AND json_extract_string(payload, '$.high')  IS NOT NULL
              AND json_extract_string(payload, '$.low')   IS NOT NULL
              AND json_extract_string(payload, '$.close') IS NOT NULL
            ORDER BY date
            """,
            [ticker],
        )
        return con.execute(
            "SELECT COUNT(*) FROM staging.stg_prices_daily WHERE ticker = ?", [ticker]
        ).fetchone()[0]


def rebuild_fred_market(warehouse: Warehouse) -> int:
    """Typed FRED index observations: raw's string `value` → DOUBLE, dropping
    the "." missing-value sentinel. Market-wide (not per ticker): the full
    table is rebuilt from raw each run — a few thousand rows, idempotent on
    the (series, date) PK."""
    with warehouse.connect() as con:
        con.execute("DELETE FROM staging.stg_fred_market")
        con.execute(
            """
            INSERT INTO staging.stg_fred_market (series, date, value)
            SELECT
                series,
                date,
                TRY_CAST(json_extract_string(payload, '$.value') AS DOUBLE)
            FROM raw.raw_fred_market
            WHERE TRY_CAST(json_extract_string(payload, '$.value') AS DOUBLE) IS NOT NULL
            """
        )
        return con.execute("SELECT COUNT(*) FROM staging.stg_fred_market").fetchone()[0]