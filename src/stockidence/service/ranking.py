from __future__ import annotations

from .models import RankedTicker
from .warehouse import _resilient

# Static fallback mirroring the notebook's latest-cohort head, so the
# rankings section renders before the warehouse seed lands (fresh checkout
# without a schema init). Scores are ordinal within-quarter ranks, not
# expected returns.
_DEMO_RANKINGS: list[dict] = [
    {"rank": 1, "ticker": "MRNA", "sector": "Healthcare", "score": 1.0055},
    {"rank": 2, "ticker": "CNC", "sector": "Healthcare", "score": 0.7826},
    {"rank": 3, "ticker": "DKNG", "sector": "Consumer Discretionary", "score": 0.7199},
    {"rank": 4, "ticker": "NOW", "sector": "Technology", "score": 0.6774},
    {"rank": 5, "ticker": "SMCI", "sector": "Technology", "score": 0.669},
    {"rank": 6, "ticker": "ACN", "sector": "Technology", "score": 0.6611},
    {"rank": 7, "ticker": "CSGP", "sector": "Real Estate", "score": 0.6377},
    {"rank": 8, "ticker": "TTD", "sector": "Communication Services", "score": 0.6342},
    {"rank": 9, "ticker": "EPAM", "sector": "Technology", "score": 0.5967},
    {"rank": 10, "ticker": "ZTS", "sector": "Healthcare", "score": 0.585},
]

_DEMO_AS_OF = "2026-06-30"


def _demo_rankings() -> dict:
    """Inline demo head used when the warehouse has no rankings yet."""
    items = [RankedTicker(**r).to_dict() for r in _DEMO_RANKINGS]
    return {"as_of": _DEMO_AS_OF, "universe_size": len(items), "items": items}


def get_rankings() -> dict:
    """Full ranked cohort for the latest quarter: rank/ticker/sector/score.

    Reads mart.model_rankings (seeded statically until the Dagster ranking
    job owns writes). Falls back to the inline demo head when the warehouse
    is absent or the table is empty so the UI never hard-fails.
    """
    try:
        return _fetch_rankings()
    except (FileNotFoundError, ImportError):
        # No warehouse (or no duckdb) on this host: demo fallback below.
        return _demo_rankings()


@_resilient
def _fetch_rankings() -> dict:
    """Load the ranked cohort; raises on failure (retried by decorator).

    Transient contention is retried; missing tables and other errors
    propagate to the route (unchanged behavior).
    """
    from .warehouse import read_connect

    with read_connect() as con:
        rows = con.execute(
            "SELECT as_of, rank, ticker, sector, score"
            " FROM mart.model_rankings"
            " WHERE as_of = (SELECT MAX(as_of) FROM mart.model_rankings)"
            " ORDER BY rank ASC"
        ).fetchall()
    if rows:
        as_of = rows[0][0].isoformat() if hasattr(rows[0][0], "isoformat") else str(rows[0][0])
        items = [
            RankedTicker(
                rank=int(r[1]),
                ticker=str(r[2]),
                sector=r[3],
                score=float(r[4]) if r[4] is not None else None,
            ).to_dict()
            for r in rows
        ]
        return {"as_of": as_of, "universe_size": len(items), "items": items}
    return _demo_rankings()


def _tier(rank: int, n: int) -> int:
    """Quintile tier: 0 = top fifth ... 4 = bottom fifth."""
    return min(4, (rank - 1) * 5 // max(n, 1))


@_resilient
def get_ranking_detail(ticker: str) -> dict | None:
    """One ranked stock: rank context plus how the model built its score.

    `features` holds each model input's value, the cohort median and its SHAP
    contribution (score = base_score + sum of contributions); it is empty
    until a retrain has exported contributions for the latest cohort.
    Returns None when the ticker isn't in the latest ranking.
    """
    from .warehouse import read_connect

    ticker = ticker.strip().upper()
    with read_connect() as con:
        latest = con.execute("SELECT MAX(as_of) FROM mart.model_rankings").fetchone()[0]
        if latest is None:
            return None
        row = con.execute(
            "SELECT rank, sector, score FROM mart.model_rankings WHERE as_of = ? AND ticker = ?",
            [latest, ticker],
        ).fetchone()
        if row is None:
            return None
        rank, sector, score = row
        n = con.execute(
            "SELECT COUNT(*) FROM mart.model_rankings WHERE as_of = ?", [latest]
        ).fetchone()[0]
        sector_rank, sector_n = con.execute(
            "SELECT COUNT(*) FILTER (WHERE rank <= ?), COUNT(*) FROM mart.model_rankings"
            " WHERE as_of = ? AND sector IS NOT DISTINCT FROM ?",
            [rank, latest, sector],
        ).fetchone()
        prev = con.execute(
            "SELECT r.as_of, r.rank FROM mart.model_rankings r"
            " WHERE r.ticker = ? AND r.as_of < ? ORDER BY r.as_of DESC LIMIT 1",
            [ticker, latest],
        ).fetchone()
        features, base = _explanation(con, latest, ticker)
        try:
            name = con.execute(
                "SELECT json_extract_string(payload, '$.name') FROM raw.raw_company_profile"
                " WHERE ticker = ?",
                [ticker],
            ).fetchone()
        except Exception:  # noqa: BLE001 — name is decoration; never fail the page on it
            name = None
    return _detail_payload(
        latest, ticker, name, sector, rank, n, sector_rank, sector_n, score, base, prev, features
    )


def _missing_table(exc: Exception) -> bool:
    """Explainability tables appear on the first Dagster run after deploy."""
    import duckdb

    return isinstance(exc, duckdb.CatalogException)


def _explanation(con, latest, ticker: str) -> tuple[list, float | None]:
    """(feature rows, base score) for one ticker; empty before the first export."""
    try:
        features = con.execute(
            """
            SELECT c.feature, c.value, c.contribution, m.median_value
            FROM mart.model_contributions c
            JOIN (
                SELECT feature, MEDIAN(value) AS median_value
                FROM mart.model_contributions WHERE as_of = ? GROUP BY feature
            ) m USING (feature)
            WHERE c.as_of = ? AND c.ticker = ?
            ORDER BY ABS(c.contribution) DESC
            """,
            [latest, latest, ticker],
        ).fetchall()
        base = con.execute(
            "SELECT MAX(base_score) FROM mart.model_feature_importance WHERE as_of = ?",
            [latest],
        ).fetchone()[0]
    except Exception as exc:
        if not _missing_table(exc):
            raise
        return [], None
    return features, base


def _detail_payload(
    latest, ticker, name, sector, rank, n, sector_rank, sector_n, score, base, prev, features
) -> dict:
    return {
        "as_of": latest.isoformat(),
        "ticker": ticker,
        "company_name": name[0] if name and name[0] else None,
        "sector": sector,
        "rank": int(rank),
        "universe_size": int(n),
        "tier": _tier(int(rank), int(n)),
        "percentile_above": round((n - rank) / n * 100) if n else 0,
        "sector_rank": int(sector_rank),
        "sector_size": int(sector_n),
        "score": float(score) if score is not None else None,
        "base_score": float(base) if base is not None else None,
        "previous": (
            {"as_of": prev[0].isoformat(), "rank": int(prev[1])} if prev else None
        ),
        "features": [
            {
                "feature": f,
                "value": v,
                "median": med,
                "contribution": c,
            }
            for f, v, c, med in features
        ],
    }


@_resilient
def get_model_overview() -> dict:
    """Cohort-wide input weights and the per-quarter track record."""
    from .warehouse import read_connect

    with read_connect() as con:
        try:
            latest = con.execute(
                "SELECT MAX(as_of) FROM mart.model_feature_importance"
            ).fetchone()[0]
            weights = con.execute(
                "SELECT feature, mean_abs_contribution FROM mart.model_feature_importance"
                " WHERE as_of = ? ORDER BY mean_abs_contribution DESC",
                [latest],
            ).fetchall() if latest else []
            track = con.execute(
                "SELECT quarter, top20_return, universe_return, spx_return, n_stocks, source"
                " FROM mart.model_track_record ORDER BY quarter"
            ).fetchall()
        except Exception as exc:
            if not _missing_table(exc):
                raise
            latest, weights, track = None, [], []

    total = sum(w for _, w in weights) or 1.0
    quarters = [
        {
            "quarter": q.isoformat(),
            "top20_return": t,
            "universe_return": u,
            "spx_return": s,
            "n_stocks": n,
            "source": src,
        }
        for q, t, u, s, n, src in track
    ]
    vs_spx = [q["top20_return"] - q["spx_return"] for q in quarters
              if q["top20_return"] is not None and q["spx_return"] is not None]
    return {
        "as_of": latest.isoformat() if latest else None,
        "weights": [{"feature": f, "share": w / total} for f, w in weights],
        "track_record": quarters,
        "summary": {
            "quarters": len(vs_spx),
            "avg_excess_vs_spx": sum(vs_spx) / len(vs_spx) if vs_spx else None,
            "hit_rate_vs_spx": (sum(1 for x in vs_spx if x > 0) / len(vs_spx)) if vs_spx else None,
        },
    }
