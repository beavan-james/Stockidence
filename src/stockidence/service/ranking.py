from __future__ import annotations

from pathlib import Path

from .models import RankedTicker
from .warehouse import _config_db_path

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

_DEMO_AS_OF = "2026-04-01"


def get_rankings() -> dict:
    """Full ranked cohort for the latest quarter: rank/ticker/sector/score.

    Reads mart.model_rankings (seeded statically until the Dagster ranking
    job owns writes). Falls back to the inline demo head when the warehouse
    is absent or the table is empty so the UI never hard-fails.
    """
    db_path = Path(_config_db_path())
    if db_path.exists():
        try:
            import duckdb
        except ImportError:
            duckdb = None
        if duckdb is not None:
            try:
                con = duckdb.connect(str(db_path), read_only=True)
            except Exception:
                con = None
            if con is not None:
                try:
                    rows = con.execute(
                        "SELECT as_of, rank, ticker, sector, score"
                        " FROM mart.model_rankings ORDER BY rank ASC"
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
                except Exception:
                    pass
                finally:
                    con.close()
    items = [RankedTicker(**r).to_dict() for r in _DEMO_RANKINGS]
    return {"as_of": _DEMO_AS_OF, "universe_size": len(items), "items": items}
