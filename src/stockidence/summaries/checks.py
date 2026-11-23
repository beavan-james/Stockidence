"""Checks on what the model writes. Each returns a list of problems; an
empty list passes.

The rule behind the number and ticker checks: everything the model writes
must appear in what it was given (the prompt), so a figure or ticker it
made up is caught.

- A number passes when the prompt has it, written the same way or as one
  of the words one to twelve, or when it is a rounding of a number in the
  prompt that keeps at least two significant figures (13.48 written as
  13.5 or 13 passes, 2.4 written as 2 doesn't).
- A ticker is a capitalized code in parentheses or after a $, as the
  prompts ask: "Nvidia (NVDA)", "$NVDA". It passes when the prompt has
  it as a word. Acronyms in parentheses, "(FTC)", pass the same way.
- Advice is recommendation wording, not the words "buy" and "sell" alone,
  which deal news needs ("agreed to buy").
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Not part of a word or another number: "Q3" and "v2" are labels, not figures.
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
_WORD = re.compile(r"[a-z]+")
_TICKER = re.compile(
    r"\((?:(?:NASDAQ|NYSE|AMEX|OTC)[A-Z]*\s*:\s*)?([A-Z][A-Z0-9]{0,5}(?:\.[A-Z]{1,2})?)\)"
    r"|\$([A-Z][A-Z0-9]{0,5}(?:\.[A-Z]{1,2})?)\b"
)
_ADVICE = re.compile("|".join((
    r"\bshould\b",
    r"\bought to\b",
    r"\brecommend\w*\b",
    r"\b(?:strong )?(?:buy|sell|hold) (?:rating|signal|recommendation|call)s?\b",
    r"\b(?:is|as|remains|looks like) an? (?:strong )?(?:buy|sell|hold)\b",
    r"\b(?:time|worth|consider|considering|good idea|opportunity) to (?:buy|sell|hold)\b",
    r"\b(?:buy|sell) (?:the|this) (?:stock|dip|rally|shares|news)\b",
    r"\bprice targets?\b|\btarget price\b",
    r"\b(?:upgraded|downgraded|upgrades|downgrades) (?:\w+ ){0,3}to (?:buy|sell|hold|overweight|underweight|outperform|underperform)\b",
    r"\binvestors (?:may|might|could|would) (?:want|wish|do well|consider)\b",
)), re.IGNORECASE)


def _normal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    """Every number written in digits, plus one to twelve written as words."""
    found = {n for raw in _NUMBER.findall(text) if (n := _normal(raw)) is not None}
    found |= {Decimal(_NUMBER_WORDS[w]) for w in _WORD.findall(text.lower()) if w in _NUMBER_WORDS}
    return found


def _significant(n: Decimal) -> int:
    return len(n.normalize().as_tuple().digits) if n else 1


def _places(raw: str) -> int:
    return len(raw.split(".")[1]) if "." in raw else 0


def number_supported(raw: str, given: set[Decimal]) -> bool:
    n = _normal(raw)
    if n is None or n in given:
        return True
    if _significant(n) < 2:
        return False
    step = Decimal(1).scaleb(-_places(raw))
    return any(_rounds_to(g, step, n) for g in given)


def _rounds_to(g: Decimal, step: Decimal, n: Decimal) -> bool:
    try:
        return g.quantize(step, rounding=ROUND_HALF_UP) == n
    except InvalidOperation:  # too many digits to round that finely
        return False


def unsupported_numbers(text: str, given: str | set[Decimal]) -> list[str]:
    pool = numbers_in(given) if isinstance(given, str) else given
    return [raw for raw in _NUMBER.findall(text) if not number_supported(raw, pool)]


def tickers_in(text: str) -> list[str]:
    return [a or b for a, b in _TICKER.findall(text)]


def has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![\w.]){re.escape(word)}(?![\w])", text) is not None


def unsupported_tickers(text: str, given: str) -> list[str]:
    return [t for t in dict.fromkeys(tickers_in(text)) if not has_word(given, t)]


def advice(text: str) -> list[str]:
    return [m.group(0) for m in _ADVICE.finditer(text)]


def word_count(text: str) -> int:
    return len(text.split())


def check_prose(text: str, given: str, words: tuple[int, int]) -> list[str]:
    """Everything a written summary must pass, against the prompt it was given."""
    problems = []
    if bad := unsupported_numbers(text, given):
        problems.append(f"numbers not in the input: {', '.join(bad)}")
    if bad := unsupported_tickers(text, given):
        problems.append(f"tickers not in the input: {', '.join(bad)}")
    if found := advice(text):
        problems.append(f"advice wording: {', '.join(found)}")
    n = word_count(text)
    if not words[0] <= n <= words[1]:
        problems.append(f"{n} words, outside {words[0]}-{words[1]}")
    return problems
