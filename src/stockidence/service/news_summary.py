"""News summary read path: one digest's model-written text from
mart.news_summaries (stockidence.summaries writes it), each part with the
stories it was written from.

A digest counts as written when at least one of its parts has text; a
daily whose paragraph failed its checks has none, so the page goes back to
the article before it. Previous and next step through written digests; from
the first one, previous goes on to the digest before it, which has only its
story list.

A part's story_keys are card keys (article ids). Its sources are the pages
those cards were read from (mart.news_story_cards.source_url), named by
their articles in staging.stg_news_articles: headline, outlet, link.
"""

from __future__ import annotations

from datetime import date

from .digest import _iso
from .ranking import _missing_table
from .warehouse import _resilient


def _empty(period: str) -> dict:
    return {
        "period": period,
        "digest_date": None,
        "previous_date": None,
        "next_date": None,
        "session_gap_minutes": None,
        "model": None,
        "prompt_version": None,
        "created_at": None,
        "parts": [],
    }


def get_summary(period: str, digest_date: date | None = None) -> dict:
    """The daily paragraph or the weekly article (part 0 the overview, then
    its sections): the latest written one on or before `digest_date`, or the
    latest of all when no date is given.

    Empty (not an error) when there is none: before the first summary run,
    for a date before it, or when the warehouse is absent.
    """
    try:
        return _fetch(period, digest_date)
    except (FileNotFoundError, ImportError):
        return _empty(period)


# Each card key's source. A card names the page it was read from, which may
# be another article of the story than the one its key names (the lead can
# be on a site the scraper skips); a fallback card names the lead's link. A
# key with no card, or a page with no article row, falls back to the key's
# own article.
_SOURCES = """
WITH k AS (SELECT UNNEST(?::VARCHAR[]) AS story_key),
picked AS (
    SELECT k.story_key, coalesce(c.source_url, a.url) AS url,
           a.url AS own_url, a.headline AS own_headline, a.source AS own_outlet
    FROM k
    LEFT JOIN mart.news_story_cards c USING (story_key)
    LEFT JOIN staging.stg_news_articles a ON a.article_id = k.story_key
),
pages AS (
    SELECT url, arg_min(headline, published_at) AS headline,
           arg_min(source, published_at) AS outlet
    FROM staging.stg_news_articles
    WHERE url IN (SELECT url FROM picked)
    GROUP BY url
)
SELECT p.story_key,
       CASE WHEN p.url = p.own_url OR g.url IS NULL THEN p.own_headline ELSE g.headline END,
       CASE WHEN p.url = p.own_url OR g.url IS NULL THEN p.own_outlet ELSE g.outlet END,
       CASE WHEN g.url IS NULL AND p.own_url IS NOT NULL THEN p.own_url ELSE p.url END
FROM picked p
LEFT JOIN pages g USING (url)
"""


@_resilient
def _fetch(period: str, digest_date: date | None) -> dict:
    """Load the envelope; raises on failure (retried by decorator)."""
    from .warehouse import read_connect

    with read_connect() as con:
        try:
            head = con.execute(
                """
                WITH written AS (
                    SELECT digest_date FROM mart.news_summaries WHERE period = ?
                    GROUP BY digest_date HAVING bool_or(body IS NOT NULL)
                ),
                pick AS (
                    SELECT max(digest_date) AS day FROM written
                    WHERE CAST(? AS DATE) IS NULL OR digest_date <= ?
                )
                SELECT day,
                       coalesce((SELECT max(digest_date) FROM written WHERE digest_date < day),
                                (SELECT max(digest_date) FROM mart.news_digests
                                 WHERE period = ? AND digest_date < day)),
                       (SELECT min(digest_date) FROM written WHERE digest_date > day),
                       (SELECT session_gap_minutes FROM mart.news_digests
                        WHERE period = ? AND digest_date = day)
                FROM pick
                """,
                [period, digest_date, digest_date, period, period],
            ).fetchone()
            if head is None or head[0] is None:
                return _empty(period)
            rows = con.execute(
                """
                SELECT digest_date, part, heading, body, story_keys, status, model,
                       prompt_version, created_at
                FROM mart.news_summaries
                WHERE period = ? AND digest_date = ?
                ORDER BY part
                """,
                [period, head[0]],
            ).fetchall()
            keys = list(dict.fromkeys(k for row in rows for k in row[4]))
            found = {
                key: (headline, outlet, url)
                for key, headline, outlet, url in con.execute(_SOURCES, [keys]).fetchall()
            }
        except Exception as exc:
            if not _missing_table(exc):
                raise
            return _empty(period)

    def sources(story_keys) -> list[dict]:
        seen, out = set(), []
        for key in story_keys:
            headline, outlet, url = found.get(key, (None, None, None))
            if url and url not in seen:
                seen.add(url)
                out.append({"headline": headline, "outlet": outlet, "url": url})
        return out

    models = [r[6] for r in rows if r[6]]
    return {
        "period": period,
        "digest_date": _iso(head[0]),
        "previous_date": _iso(head[1]),
        "next_date": _iso(head[2]),
        "session_gap_minutes": head[3],
        "model": models[0] if models else None,
        "prompt_version": rows[0][7],
        "created_at": max(r[8] for r in rows).isoformat(),
        "parts": [
            {
                "part": part,
                "heading": heading,
                "body": body,
                "status": status,
                "sources": sources(keys or []),
            }
            for _, part, heading, body, keys, status, *_ in rows
        ],
    }
