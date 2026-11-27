"""The weekly article's sections, by rule (no model).

  1. Stories that share an article are one item (stories.group_stories),
     with every card made for them.
  2. Items leading with the same company are one thread, in date order, so
     a story that develops over several days reads as one.
  3. A thread goes to the first topic its top item belongs to (Policy and
     the economy, Earnings, Deals), else to its company's sector (the
     latest weekly rankings, then the quarterly ones), else to "Also this
     week".
  4. Topic sections keep that fixed order; sector sections follow,
     ordered by their items' summed scores. A section with fewer than
     MIN_STORIES items folds into "Also this week", which comes last.
  5. A section whose cards come to more than SECTION_TOKENS is split, a
     whole thread at a time where it can be.

Daily and weekly scores aren't on one scale, so an item takes its best
score of either. Like the digest's, these thresholds are provisional.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .cards import Card, cards_of, render_card
from .stories import StoryInput

POLICY = "Policy and the economy"
EARNINGS = "Earnings"
DEALS = "Deals"
ALSO = "Also this week"
TOPICS: tuple[tuple[str, frozenset[str]], ...] = (
    (POLICY, frozenset({"policy", "macro"})),
    (EARNINGS, frozenset({"earnings"})),
    (DEALS, frozenset({"deal"})),
)
MIN_STORIES = 2
SECTION_TOKENS = 3000


@dataclass(frozen=True)
class Item:
    """One event, told by one or more digests' stories."""

    stories: tuple[StoryInput, ...]
    cards: tuple[Card, ...]

    @property
    def score(self) -> float:
        return max(s.score for s in self.stories)

    @property
    def top(self) -> StoryInput:
        return max(self.stories, key=lambda s: s.score)

    @property
    def when(self) -> datetime:
        return min(s.published_at for s in self.stories)

    @property
    def lead_ticker(self) -> str | None:
        return self.top.tickers[0] if self.top.tickers else None

    def story_for(self, card: Card) -> StoryInput:
        return next((s for s in self.stories if card.story_key in s.article_ids), self.stories[0])

    def rendered(self) -> list[str]:
        return [render_card(c, self.story_for(c), dated=True) for c in self.cards]


@dataclass(frozen=True)
class Section:
    heading: str
    items: tuple[Item, ...]

    @property
    def story_keys(self) -> list[str]:
        return [c.story_key for item in self.items for c in item.cards]

    def rendered(self) -> str:
        return "\n\n".join(text for item in self.items for text in item.rendered())


def make_items(groups: list[list[StoryInput]], cards: dict[str, Card]) -> list[Item]:
    items = []
    for group in groups:
        have = cards_of(group, cards)
        if have:  # every group has one once the cards step has run
            items.append(Item(tuple(group), tuple(have)))
    return items


def threads(items: list[Item]) -> list[list[Item]]:
    """Items grouped by the company they lead with, each in date order;
    an item about no company is a thread of its own."""
    by_company: dict[str, list[Item]] = {}
    alone: list[list[Item]] = []
    for item in items:
        if item.lead_ticker:
            by_company.setdefault(item.lead_ticker, []).append(item)
        else:
            alone.append([item])
    return [sorted(t, key=lambda i: i.when) for t in [*by_company.values(), *alone]]


def heading_for(thread: list[Item], sectors: dict[str, str]) -> str:
    top = max(thread, key=lambda i: i.score)
    categories = {c for s in top.stories for c in s.categories}
    for heading, topic in TOPICS:
        if categories & topic:
            return heading
    return sectors.get(top.lead_ticker or "", ALSO)


def _split(
    heading: str, chunk_threads: list[list[Item]], size: Callable[[list[Item]], int]
) -> list[Section]:
    """Whole threads per part while they fit; a thread too big on its own
    is split by item."""
    parts: list[list[Item]] = [[]]
    for thread in chunk_threads:
        if size(parts[-1] + thread) <= SECTION_TOKENS:
            parts[-1] += thread
            continue
        if parts[-1]:
            parts.append([])
        for item in thread:
            if parts[-1] and size(parts[-1] + [item]) > SECTION_TOKENS:
                parts.append([])
            parts[-1].append(item)
    parts = [p for p in parts if p]
    if len(parts) == 1:
        return [Section(heading, tuple(parts[0]))]
    return [Section(f"{heading}, part {n}", tuple(p)) for n, p in enumerate(parts, start=1)]


def plan_week(
    groups: list[list[StoryInput]],
    cards: dict[str, Card],
    sectors: dict[str, str],
    count_tokens: Callable[[str], int],
) -> list[Section]:
    by_heading: dict[str, list[list[Item]]] = {}
    for thread in threads(make_items(groups, cards)):
        by_heading.setdefault(heading_for(thread, sectors), []).append(thread)

    def n_items(heading: str) -> int:
        return sum(len(t) for t in by_heading[heading])

    def summed(heading: str) -> float:
        return sum(i.score for t in by_heading[heading] for i in t)

    topics = [h for h, _ in TOPICS if h in by_heading]
    sector_names = sorted(
        (h for h in by_heading if h not in dict(TOPICS) and h != ALSO), key=lambda h: -summed(h)
    )
    kept, folded = [], list(by_heading.get(ALSO, []))
    for heading in [*topics, *sector_names]:
        if n_items(heading) >= MIN_STORIES:
            kept.append(heading)
        else:
            folded += by_heading[heading]
    order = [(h, by_heading[h]) for h in kept] + ([(ALSO, folded)] if folded else [])

    def size(items: list[Item]) -> int:
        return count_tokens("\n\n".join(t for i in items for t in i.rendered()))

    sections: list[Section] = []
    for heading, heading_threads in order:
        ranked = sorted(heading_threads, key=lambda t: -sum(i.score for i in t))
        sections += _split(heading, ranked, size)
    return sections


def names_in(section: Section, limit: int = 6) -> list[str]:
    """Who a section is about, for the other sections' prompts: company
    names (tickers when the card has none), then government bodies."""
    names: list[str] = []
    for item in section.items:
        for card in item.cards:
            c = card.card
            names += [x["name"] or x["ticker"] for x in c["companies"]] + c["government"]
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        names = [section.items[0].top.headline]
    return names[:limit]
