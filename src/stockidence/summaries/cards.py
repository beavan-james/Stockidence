"""Story cards: one model call per story turns its article into the facts
the summaries are written from (mart.news_story_cards).

The server holds the reply to CARD_SCHEMA, so it always parses. Then:
every number in the card must be in what the model was given, and every
ticker must be one of the story's or in the article. A card that fails is
asked for again at temperature 0; if that fails too, or the story has no
readable article, the card is built from the news feed's own summary and
marked `fallback`.

The weekly article reads these cards, never the articles again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .checks import has_word, unsupported_numbers
from .model import Ollama, PromptTooLong
from .prompts import CARD_SYSTEM, PROMPT_VERSION
from .stories import StoryInput, with_group_texts

MAX_OUTPUT = 600  # tokens; a full card is ~200

OK, FALLBACK = "ok", "fallback"

CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "what": {"type": "string"},
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}, "name": {"type": "string"}},
                "required": ["ticker", "name"],
            },
        },
        "government": {"type": "array", "items": {"type": "string"}},
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["label", "value", "unit"],
            },
        },
        "why_it_matters": {"type": "string"},
    },
    "required": ["what", "companies", "government", "figures", "why_it_matters"],
}


@dataclass(frozen=True)
class Card:
    story_key: str
    source_url: str | None   # the page the card was read from; the lead's link for a fallback
    card: dict[str, Any]
    status: str              # ok / fallback
    model: str | None        # None when no model output was kept
    prompt_version: str
    input_tokens: int        # all attempts
    output_tokens: int
    seconds: float
    created_at: datetime
    problems: tuple[str, ...] = field(default=(), compare=False)  # for the log, not stored


# --- prompt and checks --------------------------------------------------------

def card_prompt(story: StoryInput) -> str:
    text = story.texts[0]
    lines = [
        f"Story tickers: {', '.join(story.tickers) or 'none'}",
        f"Headline: {story.headline}",
        f"Outlet: {story.outlet or 'unknown'}",
        f"Published: {story.published_at:%Y-%m-%d %H:%M} UTC",
    ]
    if story.feed_summary:
        lines.append(f"Feed summary: {story.feed_summary}")
    lines += ["", f"Article ({text.url}):", text.text]
    return "\n".join(lines)


def tidy(card: dict[str, Any]) -> dict[str, Any]:
    """Whitespace trimmed and tickers upper-cased; nothing else changes."""
    def s(v: Any) -> str:
        return " ".join(str(v or "").split())

    return {
        "what": s(card.get("what")),
        "companies": [{"ticker": s(c.get("ticker")).upper().lstrip("$"), "name": s(c.get("name"))}
                      for c in card.get("companies") or []],
        "government": [s(g) for g in card.get("government") or [] if s(g)],
        "figures": [{"label": s(f.get("label")), "value": s(f.get("value")), "unit": s(f.get("unit"))}
                    for f in card.get("figures") or []],
        "why_it_matters": s(card.get("why_it_matters")),
    }


def card_text(card: dict[str, Any]) -> str:
    """Every string in the card, for the number check."""
    parts = [card["what"], card["why_it_matters"], *card["government"]]
    parts += [c["name"] for c in card["companies"]]
    parts += [f"{f['label']} {f['value']} {f['unit']}" for f in card["figures"]]
    return "\n".join(parts)


def check_card(card: dict[str, Any], story: StoryInput, given: str) -> list[str]:
    problems = []
    if not card["what"]:
        problems.append("empty 'what'")
    if bad := unsupported_numbers(card_text(card), given):
        problems.append(f"numbers not in the input: {', '.join(bad)}")
    if bad := [f["value"] for f in card["figures"] if not any(ch.isdigit() for ch in f["value"])]:
        problems.append(f"figures without a number: {', '.join(bad)}")
    article = story.texts[0].text
    if bad := [c["ticker"] for c in card["companies"]
               if c["ticker"] and c["ticker"] not in story.tickers and not has_word(article, c["ticker"])]:
        problems.append(f"tickers not in the story or the article: {', '.join(bad)}")
    return problems


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“‘])")


def first_sentences(text: str, max_sentences: int = 2, max_chars: int = 400) -> str:
    """The opening sentences, as many as fit both limits, and never less
    than the first: a card's `what` is one or two sentences, and some feed
    summaries run a whole paragraph."""
    sentences = _SENTENCE_END.split(" ".join(text.split()))
    kept = sentences[:1]
    for s in sentences[1:max_sentences]:
        if len(" ".join([*kept, s])) > max_chars:
            break
        kept.append(s)
    return " ".join(kept)


def fallback_card(story: StoryInput) -> dict[str, Any]:
    """What the news feed says, with no model: the feed summary's opening
    sentences (or the headline) and the story's tickers."""
    return {
        "what": first_sentences(story.feed_summary or story.headline),
        "companies": [{"ticker": t, "name": ""} for t in story.tickers],
        "government": [],
        "figures": [],
        "why_it_matters": "",
    }


# --- making one ---------------------------------------------------------------

def make_card(llm: Ollama, story: StoryInput, now: datetime, key: str | None = None) -> Card:
    """Read the story's first readable page into a card; two attempts, then
    the fallback. Raises ModelUnavailable when the server is down."""
    key = key or story.key
    if not story.texts:
        return Card(key, story.url, fallback_card(story), FALLBACK, None, PROMPT_VERSION,
                    0, 0, 0.0, now, ("no readable article",))
    given = card_prompt(story)
    problems: list[str] = []
    tokens_in = tokens_out = 0
    seconds = 0.0
    for temperature in (None, 0.0):
        try:
            reply = llm.chat(CARD_SYSTEM, given, max_output=MAX_OUTPUT,
                             temperature=temperature, schema=CARD_SCHEMA)
        except PromptTooLong as e:  # a capped article can't get here, but never cut it silently
            problems.append(str(e))
            break
        tokens_in += reply.input_tokens
        tokens_out += reply.output_tokens
        seconds += reply.seconds
        if reply.cut_off:
            problems.append("cut off at the output limit")
            continue
        try:
            card = tidy(json.loads(reply.text))
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            problems.append(f"not a card: {e}")
            continue
        found = check_card(card, story, given)
        if not found:
            return Card(key, story.texts[0].url, card, OK, llm.model, PROMPT_VERSION,
                        tokens_in, tokens_out, round(seconds, 1), now, tuple(problems))
        problems += found
    return Card(key, story.url, fallback_card(story), FALLBACK, None, PROMPT_VERSION,
                tokens_in, tokens_out, round(seconds, 1), now, tuple(problems))


# --- which stories need one ---------------------------------------------------

def cards_of(group: list[StoryInput], cards: dict[str, Card]) -> list[Card]:
    """The cards made for any story of the group, in pick order."""
    keys = dict.fromkeys(a for s in group for a in s.article_ids if a in cards)
    return [cards[k] for k in keys]


def cards_needed(groups: list[list[StoryInput]], cards: dict[str, Card],
                 redo: bool = False) -> list[tuple[str, StoryInput]]:
    """(card key, story to read) for each card to make: one for a group
    with none, and a new read of a fallback card when a readable page has
    arrived since it was made (a fetch retried later in the week). `redo`
    makes every card of these groups again."""
    jobs: list[tuple[str, StoryInput]] = []
    for group in groups:
        have = cards_of(group, cards)
        if not have:
            jobs.append((group[0].key, with_group_texts(group[0], group)))
            continue
        newest = max((t.extracted_at for s in group for t in s.texts), default=None)
        for card in have:
            stale = card.status == FALLBACK and newest is not None and newest > card.created_at
            if redo or stale:
                owner = next(s for s in group if card.story_key in s.article_ids)
                jobs.append((card.story_key, with_group_texts(owner, group)))
    return jobs


# --- shown to the writers -----------------------------------------------------

def render_card(card: Card, story: StoryInput, *, dated: bool = False) -> str:
    """A card as the daily and weekly prompts show it."""
    c = card.card
    head = f"{story.headline} ({story.outlet or 'unknown'})"
    if dated:
        head = f"{story.published_at:%a %Y-%m-%d}: {head}"
    lines = [head, f"What: {c['what']}"]
    companies = [f"{x['name']} ({x['ticker']})" if x["name"] and x["ticker"]
                 else x["name"] or x["ticker"] for x in c["companies"]]
    if companies := [x for x in companies if x]:
        lines.append(f"Companies: {', '.join(companies)}")
    if c["government"]:
        lines.append(f"Government: {', '.join(c['government'])}")
    if c["figures"]:
        lines.append("Figures: " + "; ".join(
            f"{f['label']} {f['value']} {f['unit']}".strip() for f in c["figures"]))
    if c["why_it_matters"]:
        lines.append(f"Why it matters: {c['why_it_matters']}")
    return "\n".join(lines)
