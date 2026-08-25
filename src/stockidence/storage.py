"""DuckDB persistence: schema bootstrap, raw landing, watermark tracking.

Layers follow ARCHITECTURE.md:
  raw      — landed API responses at their natural grain (e.g. one row per
             price bar), payload kept as an untouched JSON blob
  staging  — typed / cleaned / deduped (next phase)
  mart     — scored output read by the frontend
  control  — pipeline metadata (watermarks)

The raw layer doubles as the staleness-aware cache: table PKs are the
watermark grain, so re-landing the same key overwrites idempotently, and
control.watermarks records when each (endpoint, dimension) was last fetched.

Single-writer rule: all writes go through this module (i.e. through Dagster).
Readers (frontend) open their own read-only connections.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_DB_PATH = os.environ.get("STOCKIDENCE_DB", "data/stockidence.duckdb")

# artifact table -> key columns (name, duckdb type). payload + fetched_at are
# appended to every table. Keys match the registry watermark/artifact names.
RAW_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "raw_commodities": [("nominal", "VARCHAR"), ("date", "DATE")],
    "raw_macro_indicators": [("indicator", "VARCHAR"), ("date", "DATE")],
    "raw_quotes": [("ticker", "VARCHAR")],
    "raw_prices_daily": [("ticker", "VARCHAR"), ("date", "DATE")],
    "raw_stock_symbols": [("mic", "VARCHAR"), ("symbol", "VARCHAR")],
    "raw_gainers_losers": [("ticker", "VARCHAR"), ("date", "DATE")],
    "raw_ipo_calendar": [("symbol", "VARCHAR"), ("date", "DATE")],
    "raw_earnings_calendar": [("symbol", "VARCHAR"), ("quarter", "INTEGER"), ("year", "INTEGER")],
    "raw_news_articles": [("article_id", "VARCHAR")],
    "news_ticker_sentiment": [("article_id", "VARCHAR"), ("ticker", "VARCHAR")],
    # one row per ticker whose deep news history has been backfilled; the
    # staleness gate reads it as the ticker_news watermark (the shared
    # article/junction tables can't serve that role — their leading key is
    # article_id, and the daily market_news job writes into them too)
    "ticker_news_fetches": [("ticker", "VARCHAR")],
    "raw_company_profile": [("ticker", "VARCHAR")],
    # /stock/metrics lands one row PER metric per period: the metric is part
    # of the natural grain, otherwise rows in the same (quarter, year) would
    # clobber each other on the PK.
    "raw_basic_financials": [("ticker", "VARCHAR"), ("quarter", "INTEGER"), ("year", "INTEGER"), ("metric", "VARCHAR")],
    "raw_financials_reported": [
        ("ticker", "VARCHAR"),
        ("quarter", "INTEGER"),
        ("year", "INTEGER"),
    ],
    "raw_eps_surprises": [("ticker", "VARCHAR"), ("quarter", "INTEGER"), ("year", "INTEGER")],
    "raw_transcript_segments": [
        ("ticker", "VARCHAR"),
        ("quarter", "INTEGER"),
        ("year", "INTEGER"),
        ("speaker_sequence", "INTEGER"),
    ],
    "raw_insider_sentiment": [("ticker", "VARCHAR"), ("year", "INTEGER"), ("month", "INTEGER")],
    "raw_recommendation_trends": [("ticker", "VARCHAR"), ("period", "DATE")],
    "raw_peers": [("ticker", "VARCHAR")],
}


@dataclass(frozen=True)
class Watermark:
    """Most recent fetch of one (endpoint, dimension)."""

    endpoint: str
    dimension_key: str
    fetched_at: datetime
    high_watermark: str | None = None


def make_dimension_key(values: dict[str, Any], order: tuple[str, ...]) -> str:
    """Join watermark fields into a stable string key, e.g. ('AAPL',)."""
    return "|".join(str(values[k]) for k in order)


# staging-derived tables: registry derivations land here (stg_*). Staging is
# cleaning only — typed, deduped, validated. Unlike raw tables (whose dicts
# ARE the natural keys), STAGING_SCHEMA lists the full column layout — the PK
# is the (ticker, date) grain, kept separate below so rebuilds can legally
# write NULLs (first-bar returns).
STAGING_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "stg_prices_daily": [
        ("ticker", "VARCHAR"), ("date", "DATE"),
        ("open", "DOUBLE"), ("high", "DOUBLE"), ("low", "DOUBLE"), ("close", "DOUBLE"),
        ("volume", "DOUBLE"), ("return_1d", "DOUBLE"),
    ],
}


# mart tables: aggregations and derivations the scoring layer reads — resampled
# OHLCV, technical indicators, rolling/advanced analytics. Keyed (ticker, date);
# rebuilt per ticker, never appended.
MART_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "m_prices_weekly": [
        ("ticker", "VARCHAR"), ("date", "DATE"),
        ("open", "DOUBLE"), ("high", "DOUBLE"), ("low", "DOUBLE"), ("close", "DOUBLE"),
        ("volume", "DOUBLE"),
    ],
    "m_prices_monthly": [
        ("ticker", "VARCHAR"), ("date", "DATE"),
        ("open", "DOUBLE"), ("high", "DOUBLE"), ("low", "DOUBLE"), ("close", "DOUBLE"),
        ("volume", "DOUBLE"),
    ],
    "m_technical_indicators": [
        ("ticker", "VARCHAR"), ("date", "DATE"),
        ("sma_20", "DOUBLE"), ("sma_50", "DOUBLE"), ("sma_200", "DOUBLE"),
        ("ema_12", "DOUBLE"), ("ema_26", "DOUBLE"),
        ("macd", "DOUBLE"), ("macd_signal", "DOUBLE"), ("macd_hist", "DOUBLE"),
        ("rsi_14", "DOUBLE"), ("atr_14", "DOUBLE"), ("adx_14", "DOUBLE"),
        ("plus_di_14", "DOUBLE"), ("minus_di_14", "DOUBLE"),
        ("stoch_k_14", "DOUBLE"), ("stoch_d_14", "DOUBLE"), ("cci_20", "DOUBLE"),
        ("ad", "DOUBLE"), ("obv", "DOUBLE"),
        ("bb_upper_20", "DOUBLE"), ("bb_mid_20", "DOUBLE"), ("bb_lower_20", "DOUBLE"),
    ],
    "m_advanced_analytics": [
        ("ticker", "VARCHAR"), ("date", "DATE"),
        ("close", "DOUBLE"),
        ("min_252", "DOUBLE"), ("max_252", "DOUBLE"), ("mean_252", "DOUBLE"),
        ("stddev_252", "DOUBLE"), ("variance_252", "DOUBLE"), ("max_drawdown_252", "DOUBLE"),
        ("min_all", "DOUBLE"), ("max_all", "DOUBLE"), ("mean_all", "DOUBLE"),
    ],
}


# mart snapshot tables: one row per ticker, latest run wins (like the
# company-profile raw table). Written by the scoring asset on every ticker
# score; `computed_at` stamps the run for the frontend. m_rating_components
# is keyed per (ticker, category, component) — one run replaces a ticker's
# whole component set, so the key just needs to pin one row per component.
MART_SNAPSHOT_SCHEMA: dict[str, list[tuple[str, str]]] = {
    "m_confidence_ratings": [
        ("ticker", "VARCHAR"),
        ("computed_at", "TIMESTAMPTZ"),
        ("confidence_score", "DOUBLE"),
        ("rating", "VARCHAR"),
        ("valuation_score", "DOUBLE"),
        ("trend_score", "DOUBLE"),
        ("sentiment_score", "DOUBLE"),
        ("moat_score", "DOUBLE"),
        ("volatility_score", "DOUBLE"),
        ("fair_value", "DOUBLE"),
        ("target_price", "DOUBLE"),
        ("valuation_override_applied", "BOOLEAN"),
    ],
    "m_rating_components": [
        ("ticker", "VARCHAR"),
        ("computed_at", "TIMESTAMPTZ"),
        ("category", "VARCHAR"),
        ("component", "VARCHAR"),
        ("value", "DOUBLE"),
        ("weight", "DOUBLE"),
        ("source", "VARCHAR"),
    ],
    "m_buy_plans": [
        ("ticker", "VARCHAR"),
        ("computed_at", "TIMESTAMPTZ"),
        ("advised_buy_price", "DOUBLE"),
        ("stop_loss", "DOUBLE"),
        ("holding_style", "VARCHAR"),
    ],
}


def _json_default(value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class Warehouse:
    """DuckDB store for the pipeline. All writes funnel through here."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(DEFAULT_DB_PATH)

    def connect(
        self,
        read_only: bool = False,
        *,
        max_attempts: int = 40,
        base_delay: float = 0.2,
    ) -> duckdb.DuckDBPyConnection:
        """Open a connection to the DuckDB file.

        DuckDB's file lock is exclusive per process: while ANY process holds
        the file open read-write, even read_only opens are refused, and while
        any process holds it read-only, writers are refused. Parallel Dagster
        steps (and the frontend) all funnel through this store, so opens can
        transiently hit "Could not set lock on file". Both modes retry with
        backoff until the lock frees instead of crashing the run.
        """
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return duckdb.connect(str(self.path), read_only=read_only)
            except duckdb.IOException as exc:  # lock held by another process
                last_error = exc
                time.sleep(base_delay * (attempt + 1))
        raise last_error or RuntimeError("warehouse connect failed")

    def init_schema(self) -> None:
        """Idempotent bootstrap of schemas, raw tables, and watermarks."""
        with self.connect() as con:
            for schema in ("raw", "staging", "mart", "control"):
                con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS control.watermarks (
                    endpoint       VARCHAR NOT NULL,
                    dimension_key  VARCHAR NOT NULL,
                    fetched_at     TIMESTAMPTZ NOT NULL,
                    high_watermark VARCHAR,
                    PRIMARY KEY (endpoint, dimension_key)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS control.ticker_requests (
                    ticker       VARCHAR NOT NULL,
                    requested_at TIMESTAMPTZ NOT NULL,
                    status       VARCHAR NOT NULL DEFAULT 'pending',
                    PRIMARY KEY (ticker)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS control.pipeline_failures (
                    run_id        VARCHAR NOT NULL,
                    job_name      VARCHAR NOT NULL,
                    failed_at     TIMESTAMPTZ NOT NULL,
                    error_message VARCHAR,
                    PRIMARY KEY (run_id)
                )
                """
            )
            for table, keys in RAW_SCHEMA.items():
                cols = ", ".join(f'"{name}" {typ}' for name, typ in keys)
                pk = ", ".join(f'"{name}"' for name, _ in keys)
                con.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS raw."{table}" (
                        {cols},
                        payload    JSON NOT NULL,
                        fetched_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY ({pk})
                    )
                    """
                )
            for table, keys in STAGING_SCHEMA.items():
                cols = ", ".join(f'"{name}" {typ}' for name, typ in keys)
                pk = ", ".join(f'"{name}"' for name in ("ticker", "date"))
                con.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS staging."{table}" (
                        {cols},
                        PRIMARY KEY ({pk})
                    )
                    """
                )
            for table, keys in MART_SCHEMA.items():
                cols = ", ".join(f'"{name}" {typ}' for name, typ in keys)
                pk = ", ".join(f'"{name}"' for name in ("ticker", "date"))
                con.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS mart."{table}" (
                        {cols},
                        PRIMARY KEY ({pk})
                    )
                    """
                )
            for table, keys in MART_SNAPSHOT_SCHEMA.items():
                if table == "m_rating_components":
                    pk = ", ".join(f'"{name}"' for name in ("ticker", "category", "component"))
                else:
                    pk = "ticker"
                cols = ", ".join(f'"{name}" {typ}' for name, typ in keys)
                con.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS mart."{table}" (
                        {cols},
                        PRIMARY KEY ({pk})
                    )
                    """
                )
            # Presentation views over the mart snapshots: the documented
            # frontend contract (as_of/company_name mapped from the raw
            # profile snapshot, advice aliasing the rating label, and the
            # buy-plan column name from the README). The m_* tables stay the
            # storage layer; these views are the read API for the UI.
            con.execute(
                """
                CREATE OR REPLACE VIEW mart.confidence_ratings AS
                SELECT cr.ticker,
                       COALESCE(p.company_name, cr.ticker) AS company_name,
                       p.logo,
                       cr.computed_at AS as_of,
                       cr.confidence_score,
                       -- ratings are stored as 'Strong Buy' etc.; the read
                       -- contract is UPPER_SNAKE (frontend Advice enum)
                       REPLACE(UPPER(cr.rating), ' ', '_') AS advice,
                       cr.volatility_score,
                       cr.fair_value,
                       cr.target_price
                FROM mart.m_confidence_ratings cr
                LEFT JOIN (
                    SELECT ticker,
                           json_extract_string(payload, '$.name') AS company_name,
                           json_extract_string(payload, '$.logo') AS logo
                    FROM raw.raw_company_profile
                ) p USING (ticker)
                """
            )
            con.execute(
                """
                CREATE OR REPLACE VIEW mart.rating_components AS
                SELECT ticker, computed_at AS as_of, category, component,
                       value AS score, weight, source
                FROM mart.m_rating_components
                """
            )
            con.execute(
                """
                CREATE OR REPLACE VIEW mart.buy_plans AS
                SELECT ticker, computed_at AS as_of, advised_buy_price,
                       stop_loss AS stop_loss_price, holding_style
                FROM mart.m_buy_plans
                """
            )
            con.execute(
                """
                CREATE OR REPLACE VIEW mart.ticker_request_status AS
                SELECT ticker, requested_at, status
                FROM control.ticker_requests
                """
            )
            # Model category weights for the confidence blend — provisional
            # per MODEL.md, held in the warehouse so the frontend never
            # hardcodes the scoring spec.
            con.execute("CREATE TABLE IF NOT EXISTS mart.model_weights (category VARCHAR PRIMARY KEY, weight DOUBLE)")
            # CONFIDENCE_WEIGHTS (mart.scoring) is the single source of truth;
            # seeded here via a lazy import because scoring imports this module.
            # Upsert on every schema init so an already-provisioned warehouse
            # tracks the current spec instead of serving a stale snapshot.
            from .mart.scoring import CONFIDENCE_WEIGHTS

            _seed_rows = ", ".join(
                f"('{cat}', {float(w)!r})" for cat, w in CONFIDENCE_WEIGHTS.items()
            )
            con.execute(
                f"""
                INSERT INTO mart.model_weights (category, weight) VALUES {_seed_rows}
                ON CONFLICT (category) DO UPDATE SET weight = excluded.weight
                """
            )
            # Category-level contract for the rating breakdown: one row per
            # (ticker, category) with the confidence blend's category weight —
            # NOT the component rows (which carry within-category sub-weights).
            con.execute(
                """
                CREATE OR REPLACE VIEW mart.category_scores AS
                SELECT cr.ticker, cr.computed_at AS as_of,
                       c.category,
                       CAST(CASE c.category
                           WHEN 'valuation' THEN cr.valuation_score
                           WHEN 'trend'     THEN cr.trend_score
                           WHEN 'sentiment' THEN cr.sentiment_score
                           WHEN 'moat'      THEN cr.moat_score
                       END AS DOUBLE) AS score,
                       COALESCE(w.weight, 0) AS weight
                FROM mart.m_confidence_ratings cr
                CROSS JOIN (
                    SELECT 'valuation' AS category
                    UNION ALL SELECT 'trend'
                    UNION ALL SELECT 'sentiment'
                    UNION ALL SELECT 'moat'
                ) c
                LEFT JOIN mart.model_weights w USING (category)
                """
            )

    def land(
        self,
        artifact: str,
        rows: list[dict[str, Any]],
        *,
        fetched_at: datetime | None = None,
        high_watermark: str | None = None,
    ) -> int:
        """Upsert raw rows idempotently keyed on the artifact's PK columns.

        Each row keeps its full original response fragment as JSON `payload`
        (raw is minimally transformed by design). Returns rows written.
        """
        if artifact not in RAW_SCHEMA:
            raise KeyError(f"unknown artifact table: {artifact}")
        keys = [name for name, _ in RAW_SCHEMA[artifact]]
        pk = ", ".join(f'"{name}"' for name in keys)
        fetched_at = fetched_at or datetime.now(timezone.utc)
        set_cols = ", ".join(f'"{name}" = excluded."{name}"' for name in ("payload", "fetched_at"))

        written = 0
        with self.connect() as con:
            for row in rows:
                missing = [k for k in keys if k not in row]
                if missing:
                    raise KeyError(f"{artifact}: rows missing key columns {missing}")
                values = [row[k] for k in keys]
                payload_json = row.get("payload", row)
                con.execute(
                    f"""
                    INSERT INTO raw."{artifact}" ({', '.join(f'"{k}"' for k in keys)}, payload, fetched_at)
                    VALUES ({', '.join('?' for _ in keys)}, CAST(? AS JSON), ?)
                    ON CONFLICT ({pk}) DO UPDATE SET {set_cols}
                    """,
                    [*values, json.dumps(payload_json, default=_json_default), fetched_at],
                )
                written += 1

        self._touch_watermarks_for(artifact, keys, high_watermark, fetched_at)
        return written

    def _touch_watermarks_for(
        self,
        artifact: str,
        keys: list[str],
        high_watermark: str | None,
        fetched_at: datetime,
    ) -> None:
        """Maintain dimension-level watermarks from grain-level lands.

        One watermark per distinct leading key value (typically the ticker),
        so the staleness gate can look up (endpoint, "AAPL") instead of
        walking every grain row — e.g. landing prices.daily bars for AAPL
        bumps the ("raw.raw_prices_daily", "AAPL") watermark. A single
        fetch of 500 bars must not create 500 watermark rows.
        """
        with self.connect() as con:
            dimension_col = f'"{keys[0]}"'
            distinct = con.execute(
                f"SELECT DISTINCT {dimension_col} FROM raw.\"{artifact}\""
            ).fetchall()
            for (dim,) in distinct:
                self.upsert_watermark(
                    f"raw.{artifact}",
                    str(dim),
                    fetched_at=fetched_at,
                    high_watermark=high_watermark,
                )

    def get_watermark(self, endpoint: str, dimension_key: str) -> Watermark | None:
        with self.connect(read_only=True) as con:
            row = con.execute(
                """
                SELECT endpoint, dimension_key, fetched_at, high_watermark
                FROM control.watermarks
                WHERE endpoint = ? AND dimension_key = ?
                """,
                [endpoint, dimension_key],
            ).fetchone()
        if row is None:
            return None
        fetched_at = row[2]
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        return Watermark(endpoint=row[0], dimension_key=row[1], fetched_at=fetched_at, high_watermark=row[3])

    def upsert_watermark(
        self,
        endpoint: str,
        dimension_key: str,
        *,
        fetched_at: datetime | None = None,
        high_watermark: str | None = None,
    ) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO control.watermarks (endpoint, dimension_key, fetched_at, high_watermark)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (endpoint, dimension_key)
                DO UPDATE SET fetched_at = excluded.fetched_at,
                              high_watermark = COALESCE(excluded.high_watermark, control.watermarks.high_watermark)
                """,
                [endpoint, dimension_key, fetched_at, high_watermark],
            )

    # --- ticker request queue (frontend -> Dagster sensor) ---

    def request_ticker(self, ticker: str, *, requested_at: datetime | None = None) -> None:
        """Queue a ticker lookup request; re-requesting resets it to pending.

        The frontend writes here (control metadata, exempt from the
        single-writer rule); the Dagster sensor consumes the queue.
        """
        requested_at = requested_at or datetime.now(timezone.utc)
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO control.ticker_requests (ticker, requested_at, status)
                VALUES (?, ?, 'pending')
                ON CONFLICT (ticker)
                DO UPDATE SET requested_at = excluded.requested_at,
                              status = 'pending'
                """,
                [ticker, requested_at],
            )

    def pending_ticker_requests(self) -> list[str]:
        with self.connect(read_only=True) as con:
            rows = con.execute(
                """
                SELECT ticker FROM control.ticker_requests
                WHERE status = 'pending'
                ORDER BY requested_at
                """
            ).fetchall()
        return [row[0] for row in rows]

    def mark_ticker_requests_launched(self, tickers: list[str]) -> None:
        if not tickers:
            return
        with self.connect() as con:
            con.execute(
                """
                UPDATE control.ticker_requests
                SET status = 'launched'
                WHERE ticker = ANY(?)
                """,
                [tickers],
            )