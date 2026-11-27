"""The two model steps the digest jobs run, on inputs already read from the
warehouse (store.read_inputs). Neither touches the warehouse.

If the model server goes away mid-run, each step stops and returns what it
finished with the error, so the save step can keep the finished work and
then fail the run. A weekly article is only returned whole.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .cards import Card, cards_needed, cards_of, make_card
from .market import market_block
from .model import ModelUnavailable, Ollama
from .plan import plan_week
from .store import Digest, SummaryInputs
from .stories import StoryInput, group_stories
from .writing import OK, Summary, write_daily, write_weekly

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class CardRun:
    made: tuple[Card, ...]
    error: str | None = None


@dataclass(frozen=True)
class SummaryRun:
    written: tuple[Summary, ...]
    skipped: tuple[Digest, ...]     # already written from the same stories
    empty: tuple[Digest, ...]       # no stories to write about
    error: str | None = None


def make_cards(llm: Ollama, inputs: SummaryInputs, clock: Clock, *, redo: bool = False,
               on_card: Callable[[Card], None] | None = None) -> CardRun:
    made: list[Card] = []
    groups = group_stories(list(inputs.stories))
    try:
        for key, story in cards_needed(groups, inputs.cards, redo):
            card = make_card(llm, story, clock(), key)
            made.append(card)
            if on_card:
                on_card(card)
    except ModelUnavailable as e:
        return CardRun(tuple(made), str(e))
    return CardRun(tuple(made))


def _done(existing: tuple[Summary, ...] | None, keys: list[str]) -> bool:
    """Already written, every part of it, from the same stories and market
    headlines."""
    if not existing or any(s.status != OK for s in existing):
        return False
    return {k for s in existing for k in s.story_keys} == set(keys)


def daily_cards(day: date, inputs: SummaryInputs, cards: dict[str, Card]) -> list[tuple[StoryInput, Card]]:
    """The day's stories in rank order, each with its own card, or with the
    card of the story it joins up with in another digest."""
    groups = group_stories(list(inputs.stories))
    group_of = {id(s): g for g in groups for s in g}
    pairs = []
    for story in sorted((s for s in inputs.stories if s.period == "daily" and s.digest_date == day),
                        key=lambda s: s.rank):
        own = [cards[a] for a in story.article_ids if a in cards]
        found = own or cards_of(group_of[id(story)], cards)
        if found:
            pairs.append((story, found[0]))
    return pairs


def week_stories(friday: date, inputs: SummaryInputs) -> list[StoryInput]:
    """The weekly digest's stories and those of the week's daily digests."""
    monday = friday - timedelta(days=4)
    return [s for s in inputs.stories
            if (s.period == "weekly" and s.digest_date == friday)
            or (s.period == "daily" and monday <= s.digest_date <= friday)]


def write_summaries(llm: Ollama, inputs: SummaryInputs, cards: dict[str, Card], clock: Clock,
                    *, redo: bool = False) -> SummaryRun:
    written: list[Summary] = []
    skipped: list[Digest] = []
    empty: list[Digest] = []
    try:
        for period, day in inputs.write:
            market = inputs.markets.get((period, day))
            headline_keys = market.keys if market_block(market, period, day) else []
            if period == "daily":
                pairs = daily_cards(day, inputs, cards)
                keys = [card.story_key for _, card in pairs]
                if not pairs:
                    empty.append((period, day))
                elif not redo and _done(inputs.summaries.get((period, day)), [*keys, *headline_keys]):
                    skipped.append((period, day))
                else:
                    written.append(write_daily(llm, day, pairs, clock(), market))
            else:
                sections = plan_week(group_stories(week_stories(day, inputs)), cards,
                                     inputs.sectors, llm.count_tokens)
                keys = [k for s in sections for k in s.story_keys]
                if not sections:
                    empty.append((period, day))
                elif not redo and _done(inputs.summaries.get((period, day)), [*keys, *headline_keys]):
                    skipped.append((period, day))
                else:
                    written += write_weekly(llm, day, sections, clock(), market)
    except ModelUnavailable as e:
        return SummaryRun(tuple(written), tuple(skipped), tuple(empty), str(e))
    return SummaryRun(tuple(written), tuple(skipped), tuple(empty))
