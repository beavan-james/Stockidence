"""The picked stories as the summaries read them, and how stories from
different digests join up.

A story picked on Tuesday is often picked again for the week, under a
different lead article, and a weekly story can gather articles that two
daily digests kept apart. Stories that share an article are the same
event, so they share their fact cards (a card is keyed by an article id).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime


@dataclass(frozen=True)
class Text:
    """A readable article page (staging.stg_news_article_text, ≥150 words)."""

    url: str
    text: str
    words: int
    extracted_at: datetime


@dataclass(frozen=True)
class StoryInput:
    period: str
    digest_date: date
    rank: int
    headline: str
    outlet: str | None
    feed_summary: str | None
    url: str  # the lead article's link
    published_at: datetime
    tickers: tuple[str, ...]
    categories: tuple[str, ...]
    score: float
    article_ids: tuple[str, ...]  # lead first, then the others earliest first
    texts: tuple[Text, ...]  # readable pages, in the same order

    @property
    def key(self) -> str:
        """The lead article's id: the key of the card made for this story."""
        return self.article_ids[0]


def _order(story: StoryInput) -> tuple:
    # the day a story was first picked comes first, a daily before the week
    return (story.digest_date, story.period != "daily", story.rank)


def group_stories(stories: list[StoryInput]) -> list[list[StoryInput]]:
    """Stories that share an article, joined (union-find on article ids).
    Each group is in pick order and the groups in order of their first pick."""
    parent = list(range(len(stories)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[str, int] = {}
    for i, story in enumerate(stories):
        for article_id in story.article_ids:
            if article_id in owner:
                parent[root(i)] = root(owner[article_id])
            else:
                owner[article_id] = i
    groups: dict[int, list[StoryInput]] = {}
    for i, story in enumerate(stories):
        groups.setdefault(root(i), []).append(story)
    ordered = [sorted(g, key=_order) for g in groups.values()]
    return sorted(ordered, key=lambda g: _order(g[0]))


def with_group_texts(story: StoryInput, group: list[StoryInput]) -> StoryInput:
    """`story` able to read any page of its group, its own first."""
    texts = {t.url: t for s in [story, *group] for t in s.texts}
    return replace(story, texts=tuple(texts.values()))
