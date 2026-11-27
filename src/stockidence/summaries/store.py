"""Warehouse reads and writes for the summaries, kept apart from the model
calls: read everything, close, call the model, open, write, close. The
DuckDB lock is held for seconds, never while the model runs.

Reads mart.news_digest_*, staging.stg_news_articles,
staging.stg_news_article_text and the rankings (sectors); writes
mart.news_story_cards and mart.news_summaries.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from ..ingest.articles import MIN_WORDS
from ..storage import Warehouse
from .cards import Card
from .stories import StoryInput, Text
from .writing import Summary

Digest = tuple[str, date]  # (period, digest_date)


@dataclass(frozen=True)
class SummaryInputs:
    stories: tuple[StoryInput, ...]  # every story of the digests read
    cards: dict[str, Card]  # existing cards for any of their articles
    sectors: dict[str, str]  # ticker -> sector, for the weekly sections
    summaries: dict[Digest, tuple[Summary, ...]]  # what the digests to write already have
    write: tuple[Digest, ...]  # the digests to write a summary for


def _keys(digests: Iterable[Digest]) -> list[str]:
    return [f"{period}|{day.isoformat()}" for period, day in digests]


def _stories(con, digests: list[Digest]) -> list[StoryInput]:
    rows = con.execute(
        """
        SELECT s.period, s.digest_date, s.rank, s.headline, s.source, s.summary, s.url,
               s.published_at, s.tickers, s.categories, s.score,
               list(n.article_id ORDER BY n.url <> s.url, n.published_at, n.article_id),
               list(n.url ORDER BY n.url <> s.url, n.published_at, n.article_id)
        FROM mart.news_digest_stories s
        JOIN mart.news_digest_articles a USING (period, digest_date, rank)
        JOIN staging.stg_news_articles n USING (article_id)
        WHERE list_contains(?, s.period || '|' || strftime(s.digest_date, '%Y-%m-%d'))
        GROUP BY ALL
        ORDER BY s.period, s.digest_date, s.rank
        """,
        [_keys(digests)],
    ).fetchall()
    urls = sorted({u for *_, us in rows for u in us})
    texts = {
        url: Text(url, text, words, extracted_at)
        for url, text, words, extracted_at in con.execute(
            """
            SELECT url, text, words, extracted_at FROM staging.stg_news_article_text
            WHERE url IN (SELECT UNNEST(?::VARCHAR[])) AND words >= ?
            """,
            [urls, MIN_WORDS],
        ).fetchall()
    }
    stories = []
    for (
        period,
        day,
        rank,
        headline,
        outlet,
        summary,
        url,
        published,
        tickers,
        categories,
        score,
        ids,
        story_urls,
    ) in rows:
        readable = tuple(texts[u] for u in dict.fromkeys(story_urls) if u in texts)
        stories.append(
            StoryInput(
                period,
                day,
                rank,
                headline,
                outlet,
                summary,
                url,
                published,
                tuple(tickers or ()),
                tuple(categories or ()),
                score,
                tuple(ids),
                readable,
            )
        )
    return stories


def _cards(con, article_ids: list[str]) -> dict[str, Card]:
    rows = con.execute(
        """
        SELECT story_key, source_url, card, status, model, prompt_version, input_tokens,
               output_tokens, seconds, created_at
        FROM mart.news_story_cards WHERE story_key IN (SELECT UNNEST(?::VARCHAR[]))
        """,
        [article_ids],
    ).fetchall()
    return {r[0]: Card(r[0], r[1], json.loads(r[2]), *r[3:]) for r in rows}


def _sectors(con, fridays: list[date]) -> dict[str, str]:
    """Each ticker's sector in the latest weekly rankings up to the week,
    then in the quarterly ones for stocks the weekly list doesn't have."""
    if not fridays:
        return {}
    last = max(fridays)
    rows = con.execute(
        """
        SELECT ticker, sector, 0 AS pick FROM mart.weekly_rankings
        WHERE as_of = (SELECT MAX(as_of) FROM mart.weekly_rankings WHERE as_of <= ?)
          AND sector IS NOT NULL
        UNION ALL
        SELECT ticker, sector, 1 FROM mart.model_rankings
        WHERE as_of = (SELECT MAX(as_of) FROM mart.model_rankings WHERE as_of <= ?)
          AND sector IS NOT NULL
        ORDER BY pick DESC
        """,
        [last, last],
    ).fetchall()
    return {ticker: sector for ticker, sector, _ in rows}  # weekly rows come last and win


def _summaries(con, digests: list[Digest]) -> dict[Digest, tuple[Summary, ...]]:
    rows = con.execute(
        """
        SELECT period, digest_date, part, heading, body, story_keys, status, model,
               prompt_version, created_at
        FROM mart.news_summaries
        WHERE list_contains(?, period || '|' || strftime(digest_date, '%Y-%m-%d'))
        ORDER BY period, digest_date, part
        """,
        [_keys(digests)],
    ).fetchall()
    found: dict[Digest, list[Summary]] = {}
    for period, day, part, heading, body, keys, *rest in rows:
        found.setdefault((period, day), []).append(
            Summary(period, day, part, heading, body, tuple(keys), *rest)
        )
    return {k: tuple(v) for k, v in found.items()}


def read_inputs(
    warehouse: Warehouse, read: Iterable[Digest], write: Iterable[Digest]
) -> SummaryInputs:
    """Everything the cards and summaries need: the stories of the digests
    `read`, with their readable pages and existing cards, and what the
    digests to `write` already have."""
    read, write = list(dict.fromkeys(read)), list(dict.fromkeys(write))
    with warehouse.connect(read_only=True) as con:
        stories = _stories(con, read) if read else []
        cards = _cards(con, sorted({a for s in stories for a in s.article_ids}))
        sectors = _sectors(con, [d for p, d in write if p == "weekly"])
        summaries = _summaries(con, write) if write else {}
    return SummaryInputs(tuple(stories), cards, sectors, summaries, tuple(write))


def save_cards(warehouse: Warehouse, cards: list[Card]) -> int:
    if not cards:
        return 0
    with warehouse.connect() as con:
        con.executemany(
            """
            INSERT OR REPLACE INTO mart.news_story_cards (story_key, source_url, card, status,
                model, prompt_version, input_tokens, output_tokens, seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    c.story_key,
                    c.source_url,
                    json.dumps(c.card),
                    c.status,
                    c.model,
                    c.prompt_version,
                    c.input_tokens,
                    c.output_tokens,
                    c.seconds,
                    c.created_at,
                ]
                for c in cards
            ],
        )
    return len(cards)


def save_summaries(warehouse: Warehouse, summaries: list[Summary]) -> int:
    """Each digest's parts replace all it had, so a weekly article planned
    into fewer sections leaves none behind."""
    if not summaries:
        return 0
    digests = list(dict.fromkeys((s.period, s.digest_date) for s in summaries))
    with warehouse.connect() as con:
        con.execute("BEGIN TRANSACTION")
        for period, day in digests:
            con.execute(
                "DELETE FROM mart.news_summaries WHERE period = ? AND digest_date = ?",
                [period, day],
            )
        con.executemany(
            """
            INSERT INTO mart.news_summaries (period, digest_date, part, heading, body, story_keys,
                status, model, prompt_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    s.period,
                    s.digest_date,
                    s.part,
                    s.heading,
                    s.body,
                    list(s.story_keys),
                    s.status,
                    s.model,
                    s.prompt_version,
                    s.created_at,
                ]
                for s in summaries
            ],
        )
        con.execute("COMMIT")
    return len(summaries)
