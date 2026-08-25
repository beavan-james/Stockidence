from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import (
    Advice,
    BuyPlan,
    CategoryScore,
    ComponentScore,
    HoldingStyle,
    Rating,
    ScoreCategory,
)


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


def _parse_holding_style(raw) -> HoldingStyle | None:
    """Map mart.buy_plans.holding_style to the enum.

    The scoring layer persists human-readable styles ('day trade',
    'long-term hold'); the enum spells them snake_case. Accept both.
    Unknown values return None so a bad style degrades the buy plan
    instead of discarding the whole rating.
    """
    normalized = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return HoldingStyle(normalized)
    except ValueError:
        return None


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
            SELECT ticker, company_name, logo, as_of, confidence_score, advice,
                   volatility_score, fair_value, target_price
            FROM mart.confidence_ratings
            WHERE ticker = ?
            ORDER BY as_of DESC
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
        if row is None:
            return None

        ticker, company_name, logo, as_of, confidence, advice, volatility = row[:7]
        fair_value = row[7] if len(row) > 7 else None
        target_price = row[8] if len(row) > 8 else None
        if isinstance(as_of, str):
            as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))

        categories = []
        for r in con.execute(
            """
            SELECT category, score, weight
            FROM mart.category_scores
            WHERE ticker = ? AND as_of = ?
            ORDER BY weight DESC
            """,
            [ticker, as_of.isoformat()],
        ).fetchall():
            cat, score, weight = r
            if isinstance(cat, str):
                cat = ScoreCategory(cat)
            categories.append(CategoryScore(category=cat, score=float(score), weight=float(weight)))

        components = []
        for r in con.execute(
            """
            SELECT category, component, score, weight, source
            FROM mart.rating_components
            WHERE ticker = ? AND as_of = ?
            ORDER BY category, weight DESC
            """,
            [ticker, as_of.isoformat()],
        ).fetchall():
            cat, component, score, weight, source = r
            if isinstance(cat, str):
                cat = ScoreCategory(cat)
            components.append(
                ComponentScore(
                    category=cat,
                    component=component,
                    score=float(score),
                    weight=float(weight),
                    source=source,
                )
            )

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
            style = _parse_holding_style(bp[2])
            if style is not None:
                buy_plan = BuyPlan(
                    advised_buy_price=float(bp[0]),
                    stop_loss_price=float(bp[1]),
                    holding_style=style,
                )

        return Rating(
            ticker=ticker,
            company_name=company_name,
            as_of=as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc),
            confidence_score=float(confidence),
            advice=Advice(advice),
            volatility_score=float(volatility),
            categories=tuple(categories),
            components=tuple(components),
            buy_plan=buy_plan,
            logo_url=logo,
            fair_value=float(fair_value) if fair_value is not None else None,
            target_price=float(target_price) if target_price is not None else None,
            source="warehouse",
        )
    except Exception:
        return None
    finally:
        con.close()


def search_tickers(query: str, limit: int = 8) -> list[dict]:
    """Ticker autocomplete from the raw stock symbol listing (Finnhub).

    Restricted to the major US listing venues so the dropdown stays relevant
    for the search bar. Returns [] when the query is too short, the warehouse
    is absent, or nothing matches.
    """
    q = query.strip()
    if not q:
        return []
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return []
    try:
        import duckdb
    except ImportError:
        return []
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return []
    try:
        rows = con.execute(
            """
            SELECT symbol, payload->>'description' AS description,
                   mic, payload->>'type' AS security_type
            FROM raw.raw_stock_symbols
            WHERE mic IN ('XNYS', 'XNAS', 'ARCX', 'XASE')
              AND (symbol ILIKE ? OR COALESCE(payload->>'description', '') ILIKE ?)
            ORDER BY symbol ILIKE ?, symbol
            LIMIT ?
            """,
            [f"{q}%", f"%{q}%", f"{q}%", limit],
        ).fetchall()
        return [
            {
                "symbol": r[0],
                "description": r[1] or "",
                "mic": r[2],
                "type": r[3] or "",
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        con.close()


def enqueue_ticker_request(ticker: str, cooldown_minutes: int = 5) -> bool | None:
    """Ask the Dagster sensor to compute this ticker.

    Returns True when the request was (re-)queued, False if already queued
    within the cooldown window, None when the warehouse itself is unavailable.
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
        row = con.execute(
            "SELECT status, requested_at FROM control.ticker_requests WHERE ticker = ?",
            [ticker.upper()],
        ).fetchone()
        if row is not None:
            status, requested_at = row
            if status in ("pending", "launched"):
                now = datetime.now(timezone.utc)
                if isinstance(requested_at, str):
                    requested_at = datetime.fromisoformat(requested_at)
                if requested_at.tzinfo is None:
                    requested_at = requested_at.replace(tzinfo=timezone.utc)
                if now - requested_at < timedelta(minutes=cooldown_minutes):
                    con.close()
                    return False
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


def get_model_weights() -> list[dict]:
    """Category weights of the confidence blend, heaviest first.

    Reads mart.model_weights (kept in sync with scoring.CONFIDENCE_WEIGHTS
    by the pipeline's schema init). Falls back to the current spec inline
    when the warehouse is absent so the landing page still renders.
    """
    defaults = [
        {"category": "valuation", "weight": 0.62},
        {"category": "trend", "weight": 0.24},
        {"category": "sentiment", "weight": 0.10},
        {"category": "moat", "weight": 0.04},
    ]
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return defaults
    try:
        import duckdb
    except ImportError:
        return defaults
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return defaults
    try:
        rows = con.execute(
            "SELECT category, weight FROM mart.model_weights ORDER BY weight DESC"
        ).fetchall()
        if not rows:
            return defaults
        return [{"category": r[0], "weight": float(r[1])} for r in rows]
    except Exception:
        return defaults
    finally:
        con.close()


def ticker_exists(ticker: str) -> bool | None:
    """Coverage check against raw_stock_symbols (same US venue filter as
    the autocomplete, so suggestions and validation always agree).

    Returns None when existence can't be determined (no DB or table not
    landed yet) — callers should skip validation in that case rather than
    block every search.
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
            SELECT 1 FROM raw.raw_stock_symbols
            WHERE symbol = ? AND mic IN ('XNYS', 'XNAS', 'ARCX', 'XASE')
            LIMIT 1
            """,
            [ticker.upper()],
        ).fetchone()
        return row is not None
    except Exception:
        return None
    finally:
        con.close()


def get_recent_failures(days: int = 7, limit: int = 5) -> list[dict]:
    """Recent failed pipeline runs from control.pipeline_failures.

    Written by the daemon-run failure sensor; empty list when the table is
    missing/empty or the warehouse is unavailable — the UI treats that as
    'no recent failures' rather than an error.
    """
    db_path = Path(_config_db_path())
    if not db_path.exists():
        return []
    try:
        import duckdb
    except ImportError:
        return []
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return []
    try:
        rows = con.execute(
            """
            SELECT job_name, failed_at, error_message
            FROM control.pipeline_failures
            WHERE failed_at >= CURRENT_TIMESTAMP - INTERVAL (?) DAY
            ORDER BY failed_at DESC
            LIMIT ?
            """,
            [days, limit],
        ).fetchall()
        return [
            {
                "job_name": r[0],
                "failed_at": r[1].isoformat() if r[1] else "",
                "failed_at_display": (
                    r[1].strftime("%Y-%m-%d %H:%M") + " UTC" if r[1] else ""
                ),
                "error": (r[2] or "").splitlines()[0][:160],
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        con.close()