"""Stocks of the Week read path: this week's list, last week's results and
the walk-forward backtest, from the tables stockidence.weekly exports."""

from __future__ import annotations

from datetime import date, timedelta

from .ranking import _missing_table
from .warehouse import _resilient


def _iso(d) -> str | None:
    return d.isoformat() if hasattr(d, "isoformat") else (str(d) if d is not None else None)


def _week_of(as_of: date) -> str:
    """Friday snapshot -> the Monday of the week the list is for."""
    return (as_of + timedelta(days=3)).isoformat()


def _empty() -> dict:
    return {"as_of": None, "week_of": None, "universe_size": 0, "items": [],
            "previous": None, "backtest": None, "live": None, "validation": None}


def get_weekly() -> dict:
    """Envelope for the weekly page; empty (not an error) before the first
    Friday run or when the warehouse is absent."""
    try:
        return _fetch_weekly()
    except (FileNotFoundError, ImportError):
        return _empty()


def _summary(rows: list[tuple]) -> dict:
    """Average weekly lead of the top 10 over the S&P 500 and the list, and
    the share of weeks beating the index. rows: (top10, universe, spx)."""
    vs_spx = [t - s for t, _, s in rows if t is not None and s is not None]
    vs_uni = [t - u for t, u, _ in rows if t is not None and u is not None]
    return {
        "weeks": len(rows),
        "avg_excess_vs_spx": sum(vs_spx) / len(vs_spx) if vs_spx else None,
        "hit_rate_vs_spx": sum(1 for x in vs_spx if x > 0) / len(vs_spx) if vs_spx else None,
        "avg_excess_vs_universe": sum(vs_uni) / len(vs_uni) if vs_uni else None,
    }


@_resilient
def _fetch_weekly() -> dict:
    """Load the envelope; raises on failure (retried by decorator)."""
    from .warehouse import read_connect

    with read_connect() as con:
        try:
            dates = [d for (d,) in con.execute(
                "SELECT DISTINCT as_of FROM mart.weekly_rankings ORDER BY as_of DESC LIMIT 2"
            ).fetchall()]
        except Exception as exc:
            if not _missing_table(exc):
                raise
            return _empty()
        if not dates:
            return _empty()
        latest = dates[0]
        prev = dates[1] if len(dates) > 1 else None

        items = con.execute(
            """
            SELECT r.rank, r.ticker, r.sector, r.score, p.rank
            FROM mart.weekly_rankings r
            LEFT JOIN mart.weekly_rankings p ON p.ticker = r.ticker AND p.as_of = ?
            WHERE r.as_of = ?
            ORDER BY r.rank
            """,
            [prev, latest],
        ).fetchall()
        prev_items = con.execute(
            "SELECT rank, ticker, sector, realized_return FROM mart.weekly_rankings"
            " WHERE as_of = ? AND rank <= 10 ORDER BY rank",
            [prev],
        ).fetchall() if prev else []
        prev_week = con.execute(
            "SELECT top10_return, universe_return, spx_return FROM mart.weekly_track_record"
            " WHERE week = ? AND source = 'live'",
            [prev],
        ).fetchone() if prev else None
        track = con.execute(
            "SELECT week, source, top10_return, universe_return, spx_return"
            " FROM mart.weekly_track_record ORDER BY week"
        ).fetchall()
        cur = con.execute("SELECT * FROM mart.weekly_validation ORDER BY run_at DESC LIMIT 1")
        row = cur.fetchone()
        validation = (
            {c[0]: (_iso(v) if hasattr(v, "isoformat") else v) for c, v in zip(cur.description, row)}
            if row else None
        )

    backtest = [r for r in track if r[1] == "backtest"]
    live = [r for r in track if r[1] == "live"]
    return {
        "as_of": _iso(latest),
        "week_of": _week_of(latest),
        "universe_size": len(items),
        "items": [
            {"rank": int(rk), "ticker": t, "sector": s,
             "score": round(float(sc), 4) if sc is not None else None,
             "previous_rank": int(p) if p is not None else None}
            for rk, t, s, sc, p in items
        ],
        "previous": {
            "as_of": _iso(prev),
            "week_of": _week_of(prev),
            "top10_return": prev_week[0] if prev_week else None,
            "universe_return": prev_week[1] if prev_week else None,
            "spx_return": prev_week[2] if prev_week else None,
            "items": [
                {"rank": int(rk), "ticker": t, "sector": s, "realized_return": ret}
                for rk, t, s, ret in prev_items
            ],
        } if prev else None,
        "backtest": {
            **_summary([r[2:] for r in backtest]),
            "track": [
                {"week": _iso(w), "top10_return": t, "universe_return": u, "spx_return": s}
                for w, _, t, u, s in backtest
            ],
        } if backtest else None,
        "live": _summary([r[2:] for r in live]) if live else None,
        "validation": validation,
    }
