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
  it as a word. Acronyms in parentheses, "(FTC)", pass the same way. The
  writers drop one in parentheses that the prompt doesn't have before
  checking (drop_unsupported_tickers), so only a $ ticker can fail.
- A name is a capitalized word that doesn't start a sentence. It passes
  when the prompt has it in any case, or it is a day, month, title or
  other word in _FREE_NAMES, so "Michael Boehly" fails when the prompt
  only says "Boehly".
- Advice is recommendation wording, not the words "buy" and "sell" alone,
  which deal news needs ("agreed to buy").
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Not part of a word or another number: "Q3" and "v2" are labels, not figures.
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
_WORD = re.compile(r"[a-z]+")
_CODE = r"[A-Z][A-Z0-9]{0,5}(?:\.[A-Z]{1,2})?"
_IN_PARENS = rf"\((?:(?:NASDAQ|NYSE|AMEX|OTC)[A-Z]*\s*:\s*)?({_CODE})\)"
_TICKER = re.compile(rf"{_IN_PARENS}|\$({_CODE})\b")
_PAREN_TICKER = re.compile(rf"[ \t]*{_IN_PARENS}")
_ADVICE = re.compile(
    "|".join(
        (
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
        )
    ),
    re.IGNORECASE,
)


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


def drop_unsupported_tickers(text: str, given: str) -> tuple[str, list[str]]:
    """The text without the tickers in parentheses that the prompt doesn't
    have, and those tickers: "Nvidia (NVDA) rose" becomes "Nvidia rose".
    The model knows most tickers but only the given ones are checked, so an
    unchecked one is dropped rather than the whole text. A $ ticker is part
    of its sentence, so it stays for the ticker check to reject."""
    dropped: list[str] = []

    def drop(m: re.Match) -> str:
        if has_word(given, m.group(1)):
            return m.group(0)
        dropped.append(m.group(1))
        return ""

    return _PAREN_TICKER.sub(drop, text), list(dict.fromkeys(dropped))


# Capitalized words the text may use that the prompt needn't have: day and
# month names, titles written before a name, company suffixes and common
# acronyms. Provisional, like the advice list.
_FREE_NAMES = frozenset(
    w.lower()
    for w in (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        "President",
        "Vice",
        "Chair",
        "Chairman",
        "Chairwoman",
        "Governor",
        "Senator",
        "Secretary",
        "Minister",
        "Prime",
        "Chief",
        "Executive",
        "Officer",
        "CEO",
        "CFO",
        "Inc",
        "Corp",
        "Co",
        "Ltd",
        "LLC",
        "PLC",
        "GDP",
        "CPI",
        "EPS",
        "IPO",
        "ETF",
        "AI",
        "Wall",
        "Street",
    )
)
# Long forms of names the feed writes short, free when the prompt has the
# short form: "United States" when it says "US".
_LONG_FORMS = {
    "us": ("united", "states", "america"),
    "uk": ("united", "kingdom", "britain"),
    "eu": ("european", "union"),
    "fed": ("federal", "reserve"),
}
_EDGES = "\"'“”‘’()[]{},;:!?*"
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
_JOINER = re.compile(r"[-/–—]")


def _name_parts(raw: str) -> list[str]:
    """A word as names are compared: edge punctuation, a closing full stop,
    a possessive and inner dots removed ("U.S." is "US", "Korea's" is
    "Korea"), then split at hyphens and slashes ("US-backed")."""
    word = raw.strip(_EDGES).rstrip(".")
    word = re.sub(r"['’]s?$", "", word).replace(".", "")
    return [p for p in _JOINER.split(word) if p]


def unsupported_names(text: str, given: str) -> list[str]:
    """Capitalized words the prompt doesn't have (in any case): names the
    model added from memory, like a first name the headline didn't give or
    an official the headline names only by title. A sentence's first word
    isn't checked, since every sentence starts with a capital; words with
    digits are labels, like Q3."""
    known = {p.lower() for raw in given.split() for p in _name_parts(raw)} | _FREE_NAMES
    for short, long_form in _LONG_FORMS.items():
        if short in known:
            known.update(long_form)
    bad: list[str] = []
    starts_sentence = True
    for raw in text.split():
        if not starts_sentence:
            bad += [
                p
                for p in _name_parts(raw)
                if len(p) > 1
                and p[0].isupper()
                and not any(c.isdigit() for c in p)
                and p.lower() not in known
            ]
        starts_sentence = _SENTENCE_END.search(raw) is not None
    return list(dict.fromkeys(bad))


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
    if bad := unsupported_names(text, given):
        problems.append(f"names not in the input: {', '.join(bad)}")
    if found := advice(text):
        problems.append(f"advice wording: {', '.join(found)}")
    n = word_count(text)
    if not words[0] <= n <= words[1]:
        problems.append(f"{n} words, outside {words[0]}-{words[1]}")
    return problems
