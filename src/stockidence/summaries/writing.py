"""The daily paragraph and the weekly article, written from the cards
(mart.news_summaries).

Each call is checked against the prompt it was given (checks.check_prose):
numbers, tickers, names, length and advice wording. A ticker in parentheses
that the prompt doesn't have is dropped from the text first, not counted as
a failure, since the model adds the ones it knows. A failure is asked for again
at temperature 0, with the names the first answer added listed for the model
to leave out (prompts.RETRY_NAMES); if that fails too, the part is stored with status
`sources_only` and no body, and the page shows that part's sources instead.

The daily paragraph and the weekly overview end with the digest's Market
block when it has one (market.market_block); their story_keys then carry
the market headlines' article ids after the cards' keys.

Lengths: the prompts ask for the spec's word counts, and the check allows
LENGTH_SLACK either side, since a small model doesn't count words exactly.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .cards import Card, render_card
from .checks import check_prose, drop_unsupported_tickers, unsupported_names
from .market import Market, market_block
from .model import Ollama, PromptTooLong
from .plan import Section, names_in
from .prompts import (
    DAILY_SYSTEM,
    OVERVIEW_SYSTEM,
    PROMPT_VERSION,
    RETRY_NAMES,
    SECTION_SYSTEM,
)
from .stories import StoryInput

DAILY_WORDS = (150, 200)
SECTION_WORDS = (300, 600)
OVERVIEW_WORDS = (120, 180)
LENGTH_SLACK = 0.15
# Output caps in tokens: ~1.4 tokens a word with room to spare.
DAILY_OUTPUT = 450
SECTION_OUTPUT = 1100
OVERVIEW_OUTPUT = 400

OK, SOURCES_ONLY = "ok", "sources_only"

_LIST_OR_HEADING = re.compile(r"^\s*(?:#|[-*•]\s|\d+[.)]\s)", re.MULTILINE)


@dataclass(frozen=True)
class Summary:
    period: str
    digest_date: date
    part: int  # 0: the daily paragraph or the weekly overview; 1..n: sections
    heading: str | None
    body: str | None  # None when only the sources are shown
    story_keys: tuple[str, ...]
    status: str
    model: str | None
    prompt_version: str
    created_at: datetime
    problems: tuple[str, ...] = field(default=(), compare=False)  # for the log, not stored


def allowed(words: tuple[int, int]) -> tuple[int, int]:
    return (math.floor(words[0] * (1 - LENGTH_SLACK)), math.ceil(words[1] * (1 + LENGTH_SLACK)))


def tidy_prose(text: str, paragraphs: bool) -> str:
    """Bold markers dropped and whitespace evened out; one paragraph unless
    `paragraphs`."""
    text = text.replace("**", "").replace("__", "").strip()
    if not paragraphs:
        return " ".join(text.split())
    blocks = [" ".join(b.split()) for b in re.split(r"\n\s*\n", text)]
    return "\n\n".join(b for b in blocks if b)


def write(
    llm: Ollama,
    system: str,
    given: str,
    *,
    words: tuple[int, int],
    max_output: int,
    paragraphs: bool,
) -> tuple[str | None, list[str]]:
    """Two attempts at a checked piece of prose: (text, problems). The text
    is None when neither passed. Raises ModelUnavailable when the server is down."""
    problems: list[str] = []
    bounds = allowed(words)
    prompt = given
    for temperature in (None, 0.0):
        try:
            reply = llm.chat(system, prompt, max_output=max_output, temperature=temperature)
        except PromptTooLong as e:
            return None, [*problems, str(e)]
        if reply.cut_off:
            problems.append("cut off at the output limit")
            continue
        if _LIST_OR_HEADING.search(reply.text):
            problems.append("headings or lists")
            continue
        text = tidy_prose(reply.text, paragraphs)
        text, dropped = drop_unsupported_tickers(text, given)
        if dropped:
            problems.append(f"dropped tickers not in the input: {', '.join(dropped)}")
        found = check_prose(text, given, bounds)
        if not found:
            return text, problems
        problems += found
        if names := unsupported_names(text, given):
            prompt = f"{given}\n\n{RETRY_NAMES.format(names=', '.join(names))}"
    return None, problems


def _summary(
    period: str,
    day: date,
    part: int,
    heading: str | None,
    text: str | None,
    keys: list[str],
    llm: Ollama,
    now: datetime,
    problems: list[str],
) -> Summary:
    return Summary(
        period,
        day,
        part,
        heading,
        text,
        tuple(keys),
        OK if text else SOURCES_ONLY,
        llm.model if text else None,
        PROMPT_VERSION,
        now,
        tuple(problems),
    )


# --- daily --------------------------------------------------------------------

def daily_prompt(day: date, stories: list[tuple[StoryInput, Card]],
                 market: Market | None = None) -> str:
    header = (f"Daily market news summary for {day:%A %Y-%m-%d}, covering the news "
              "up to 07:00 New York time. Fact cards, most important first:")
    cards = [f"{n}. {render_card(card, story)}" for n, (story, card) in enumerate(stories, start=1)]
    block = market_block(market, "daily", day)
    return "\n\n".join([header, *cards, *([block] if block else [])])


def _with_market(keys: list[str], market: Market | None, period: str, day: date) -> list[str]:
    """Part 0's keys: the cards', then the market headlines' when the
    prompt had a Market block."""
    if market is None or not market_block(market, period, day):
        return keys
    return [*keys, *(k for k in market.keys if k not in keys)]


def write_daily(llm: Ollama, day: date, stories: list[tuple[StoryInput, Card]],
                now: datetime, market: Market | None = None) -> Summary:
    """The day's paragraph from its stories' cards, in rank order, and the
    market beside them."""
    given = daily_prompt(day, stories, market)
    text, problems = write(llm, DAILY_SYSTEM, given, words=DAILY_WORDS,
                           max_output=DAILY_OUTPUT, paragraphs=False)
    keys = _with_market([card.story_key for _, card in stories], market, "daily", day)
    return _summary("daily", day, 0, None, text, keys, llm, now, problems)


# --- weekly -------------------------------------------------------------------


def _week(friday: date) -> str:
    monday = friday - timedelta(days=4)
    return f"the week of {monday:%A %Y-%m-%d} to {friday:%A %Y-%m-%d}"


def section_prompt(friday: date, section: Section, others: list[Section]) -> str:
    lines = [
        f"Weekly market news article for {_week(friday)}.",
        f"This section: {section.heading}",
        "",
        "Fact cards:",
        "",
        section.rendered(),
    ]
    if others:
        lines += ["", "Other sections:"]
        lines += [f"- {o.heading}: {', '.join(names_in(o))}" for o in others]
    return "\n".join(lines)


def overview_prompt(friday: date, sections: list[Section], market: Market | None = None) -> str:
    lines = [f"Weekly market news article for {_week(friday)}. Its sections:"]
    for section in sections:
        lines += ["", section.heading]
        lines += [f"- {card.card['what']}" for item in section.items for card in item.cards]
    if block := market_block(market, "weekly", friday):
        lines += ["", block]
    return "\n".join(lines)


def write_weekly(llm: Ollama, friday: date, sections: list[Section], now: datetime,
                 market: Market | None = None) -> list[Summary]:
    """One call per section, then the overview, which also gets the week's
    market; part 0 is the overview."""
    parts: list[Summary] = []
    for n, section in enumerate(sections, start=1):
        others = [o for o in sections if o is not section]
        system = SECTION_SYSTEM.format(low=SECTION_WORDS[0], high=SECTION_WORDS[1])
        text, problems = write(
            llm,
            system,
            section_prompt(friday, section, others),
            words=SECTION_WORDS,
            max_output=SECTION_OUTPUT,
            paragraphs=True,
        )
        parts.append(
            _summary(
                "weekly", friday, n, section.heading, text, section.story_keys, llm, now, problems
            )
        )
    system = OVERVIEW_SYSTEM.format(low=OVERVIEW_WORDS[0], high=OVERVIEW_WORDS[1])
    text, problems = write(llm, system, overview_prompt(friday, sections, market),
                           words=OVERVIEW_WORDS, max_output=OVERVIEW_OUTPUT, paragraphs=False)
    keys = _with_market([k for s in sections for k in s.story_keys], market, "weekly", friday)
    return [_summary("weekly", friday, 0, None, text, keys, llm, now, problems), *parts]
