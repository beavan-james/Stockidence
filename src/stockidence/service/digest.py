"""News digest read path: one day's or one week's top stories from the
tables stockidence.mart.news_digest builds, with the articles grouped under
each."""

from __future__ import annotations

from datetime import date

from .ranking import _missing_table
from .warehouse import _resilient


def _iso(d) -> str | None:
    return d.isoformat() if hasattr(d, "isoformat") else None


def _utc_iso(ts) -> str | None:
    """Digest timestamps are stored as naive UTC; say so on the wire."""
    return f"{ts.isoformat()}Z" if ts is not None else None


def _weights() -> dict[str, float]:
    """The current scoring weights (a digest built before primary sources
    was scored on LEGACY_WEIGHTS; its stories' components say so)."""
    from ..mart.news_digest import IMPORTANCE_WEIGHTS

    return dict(IMPORTANCE_WEIGHTS)


def _full_marks(period: str) -> dict[str, float]:
    """Where reaction and size stop adding to a story's score: a stock's
    move, the S&P 500's, and the market caps size runs between."""
    from ..mart.news_digest import PERIODS, SIZE_DECADES, SIZE_FROM

    spec = PERIODS[period]
    return {"move": spec.reaction_full_at, "market_move": spec.market_full_at,
            "size_from": SIZE_FROM, "size_full_at": SIZE_FROM * 10**SIZE_DECADES}


def _components(cov, rea, cat, site, event, size) -> dict[str, float]:
    """A story's inputs as it was scored: event and size from primary
    sources, or coverage and category on a digest from the news feed."""
    if event is None:
        return {"coverage": round(cov, 4), "reaction": round(rea, 4),
                "category": round(cat, 4), "on_site": round(site, 4)}
    return {"event": round(event, 4), "reaction": round(rea, 4),
            "size": round(size or 0.0, 4), "on_site": round(site, 4)}


def _empty(period: str) -> dict:
    return {"period": period, "digest_date": None, "previous_date": None, "next_date": None,
            "window_start": None, "window_end": None, "built_at": None, "articles": 0,
            "routine_dropped": 0, "commentary_dropped": 0, "stories": 0, "outlets": 0,
            "session_gap_minutes": None, "sp500_return": None, "vix": None,
            "weights": _weights(), "full_marks": _full_marks(period),
            "items": []}


def get_digest(period: str, digest_date: date | None = None) -> dict | None:
    """Envelope for one 'daily' or 'weekly' digest (the latest when no date
    is given; a weekly digest is dated by its week's Friday).

    Empty (not an error) before the first digest run or when the warehouse
    is absent; None when a specific date was asked for and has no digest.
    """
    try:
        return _fetch(period, digest_date)
    except (FileNotFoundError, ImportError):
        return None if digest_date else _empty(period)


@_resilient
def _fetch(period: str, digest_date: date | None) -> dict | None:
    """Load the envelope; raises on failure (retried by decorator)."""
    from .warehouse import read_connect

    with read_connect() as con:
        try:
            head = con.execute(
                """
                SELECT digest_date, window_start, window_end, built_at, articles,
                       routine_dropped, commentary_dropped, stories, outlets,
                       session_gap_minutes, sp500_return, vix
                FROM mart.news_digests
                WHERE period = ? AND (CAST(? AS DATE) IS NULL OR digest_date = ?)
                ORDER BY digest_date DESC LIMIT 1
                """,
                [period, digest_date, digest_date],
            ).fetchone()
        except Exception as exc:
            if not _missing_table(exc):
                raise
            return None if digest_date else _empty(period)
        if head is None:
            return None if digest_date else _empty(period)
        day = head[0]
        prev_day, next_day = con.execute(
            """
            SELECT max(digest_date) FILTER (WHERE digest_date < ?),
                   min(digest_date) FILTER (WHERE digest_date > ?)
            FROM mart.news_digests WHERE period = ?
            """,
            [day, day, period],
        ).fetchone()
        stories = con.execute(
            """
            SELECT rank, headline, summary, url, source, published_at, tickers,
                   categories, n_articles, n_outlets, move_ticker, move_return,
                   coverage, reaction, category, on_site, score, event, size
            FROM mart.news_digest_stories
            WHERE period = ? AND digest_date = ?
            ORDER BY rank
            """,
            [period, day],
        ).fetchall()
        # Every other article in each story, earliest first: the lead is
        # already the story's headline, so it is left out here.
        coverage = con.execute(
            """
            SELECT a.rank, n.source, n.headline, n.url, n.published_at
            FROM mart.news_digest_articles a
            JOIN staging.stg_news_articles n USING (article_id)
            JOIN mart.news_digest_stories s
              ON s.period = a.period AND s.digest_date = a.digest_date AND s.rank = a.rank
            WHERE a.period = ? AND a.digest_date = ? AND n.url <> s.url
            ORDER BY a.rank, n.published_at, n.article_id
            """,
            [period, day],
        ).fetchall()

    also: dict[int, list[dict]] = {}
    for rank, source, headline, url, published in coverage:
        also.setdefault(int(rank), []).append(
            {
                "source": source,
                "headline": headline,
                "url": url,
                "published_at": _utc_iso(published),
            }
        )
    return {
        "period": period,
        "digest_date": _iso(day),
        "previous_date": _iso(prev_day),
        "next_date": _iso(next_day),
        "window_start": _utc_iso(head[1]),
        "window_end": _utc_iso(head[2]),
        "built_at": _iso(head[3]),
        "articles": head[4],
        "routine_dropped": head[5],
        "commentary_dropped": head[6],
        "stories": head[7],
        "outlets": head[8],
        "session_gap_minutes": head[9],
        "sp500_return": head[10],
        "vix": head[11],
        "weights": _weights(), "full_marks": _full_marks(period),
        "items": [
            {
                "rank": int(rank),
                "headline": headline,
                "summary": summary,
                "url": url,
                "source": source,
                "published_at": _utc_iso(published),
                "tickers": list(tickers or []),
                "categories": list(categories or []),
                "n_articles": n_articles,
                "n_outlets": n_outlets,
                "move_ticker": move_ticker,
                "move_return": move_return,
                "score": round(score, 4),
                "components": _components(cov, rea, cat, site, event, size),
                "also_covered": also.get(int(rank), []),
            }
            for (rank, headline, summary, url, source, published, tickers, categories,
                 n_articles, n_outlets, move_ticker, move_return,
                 cov, rea, cat, site, score, event, size) in stories
        ],
    }
