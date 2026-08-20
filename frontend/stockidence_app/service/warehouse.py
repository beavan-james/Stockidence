from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .models import Advice, BuyPlan, CategoryScore, HoldingStyle, Rating, ScoreCategory


def _config_db_path() -> str:
    """Resolve the warehouse path relative to the repo root unless the
    STOCKIDENCE_DB env var points somewhere explicit."""
    return os.environ.get(
        "STOCKIDENCE_DB",
        str(Path(__file__).resolve().parents[3] / "data" / "stockidence.duckdb"),
    )


def is_warehouse_reachable() -> bool:
    """True when a readable mart schema is present (vs. a missing DB)."""
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return False
    try:
        import duckdb
    except ImportError:
        return False
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return False
    try:
        n = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='mart'"
        ).fetchone()[0]
        return bool(n)
    except Exception:
        return False
    finally:
        con.close()


def load_rating_from_warehouse(ticker: str) -> Rating | None:
    """Read a rating from the mart layer.

    Returns None (triggering the demo fallback) if the warehouse is absent,
    the table is missing, or the ticker has no rating yet. The mart layer is
    the only schema namespace read here — raw/staging are internal.
    """
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return None

    try:
        import duckdb
    except ImportError:
        return None

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return None

    try:
        row = con.execute(
            """
            SELECT ticker, company_name, as_of, confidence_score, advice,
                   volatility_score
            FROM mart.confidence_ratings
            WHERE ticker = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
        if row is None:
            return None

        ticker, company_name, as_of, confidence, advice, volatility = row
        if isinstance(as_of, str):
            as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))

        categories = []
        for r in con.execute(
            """
            SELECT category, score, weight
            FROM mart.rating_components
            WHERE ticker = ? AND as_of = ?
            ORDER BY weight DESC
            """,
            [ticker, as_of.isoformat()],
        ).fetchall():
            cat, score, weight = r
            if isinstance(cat, str):
                cat = ScoreCategory(cat)
            categories.append(CategoryScore(category=cat, score=float(score), weight=float(weight)))

        buy_plan = None
        bp = con.execute(
            """
            SELECT advised_buy_price, stop_loss_price, holding_style
            FROM mart.buy_plans
            WHERE ticker = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            [ticker],
        ).fetchone()
        if bp is not None and bp[2] is not None:
            buy_plan = BuyPlan(
                advised_buy_price=float(bp[0]),
                stop_loss_price=float(bp[1]),
                holding_style=HoldingStyle(bp[2]),
            )

        return Rating(
            ticker=ticker,
            company_name=company_name,
            as_of=as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc),
            confidence_score=float(confidence),
            advice=Advice(advice),
            volatility_score=float(volatility),
            categories=tuple(categories),
            buy_plan=buy_plan,
            source="warehouse",
        )
    except Exception:
        return None
    finally:
        con.close()


def enqueue_ticker_request(ticker: str) -> bool | None:
    """Ask the Dagster sensor to compute this ticker.

    Returns True when the warehouse is reachable and the request was queued
    (or re-queued), None when the warehouse itself is unavailable.
    """
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return None
    try:
        import duckdb
    except ImportError:
        return None
    try:
        con = duckdb.connect(str(db_path))
        con.execute(
            """
            INSERT INTO control.ticker_requests (ticker, requested_at, status)
            VALUES (?, current_timestamp, 'pending')
            ON CONFLICT (ticker)
            DO UPDATE SET requested_at = excluded.requested_at,
                          status = 'pending'
            """,
            [ticker.upper()],
        )
        con.close()
        return True
    except Exception:
        return None