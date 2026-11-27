"""News digests: the day's and the week's most important stories, picked
by rule.

Reads staging.stg_news_articles, plus staging.stg_prices_daily (how the
stock a story leads with moved), staging.stg_fred_market (the S&P 500 and
the VIX), raw.raw_company_profile (market caps) and the published rankings
(which stocks the site covers). Writes mart.news_digests,
news_digest_stories, news_digest_articles and news_digest_context, keyed by
period ('daily' or 'weekly') and date. No API calls (registry cadence
DERIVED).

A daily digest dated D covers the news up to 07:00 New York time on D, back
to 07:00 on the weekday before, so Monday's digest covers the weekend. A
weekly digest dated Friday F covers the seven days to 07:00 on the Saturday
after F: the week's five sessions, their evenings and the weekend before.

Stories come from primary sources only (PRIMARY_FEEDS): the tracked
companies' 8-Ks (ingest.sec_filings) and the Fed's, BLS's, SEC's and FTC's
releases (ingest.agency_feeds). Picking them:
  1. group releases about the same event: the same lead stock and category
     within 36 hours (an 8-K and its press-release follow-up), or headlines
     sharing enough rare words
  2. score each story on four inputs, each 0 to 1, by weighted sum:
       event     what happened, from EVENT_ITEMS for an 8-K (a bankruptcy
                 or restatement high, a director change low) and from the
                 release's kind for an agency (an FOMC statement or CPI
                 high, a meeting notice low)
       reaction  how the stock it leads with moved: its 1-day move in a
                 daily digest, its move over the week in a weekly one; the
                 S&P 500's move for a release that names no stock
       size      the lead stock's market cap, on a log scale from $10bn
                 (0) to $1tn (1); a Fed or BLS release counts as full size
       on_site   names a stock in one of the site's rankings
     where reaction reaches full marks is set per period
  3. keep the period's top stories (10 a day, 15 a week) that score at
     least MIN_PICK_SCORE, so a quiet day has fewer. A day keeps up to 2 of
     its places for policy or macro stories: when fewer make the top 10 on
     score, the best of the rest scoring at least 0.30 take the places of
     the lowest-ranked others

Market context: the news feed's general headlines (Finnhub) never become
stories. With what isn't news dropped (routine filings, commentary) and
articles about the same event grouped, the most covered few are kept in
news_digest_context, beside the S&P 500's and VIX's figures in
news_digests, for the summaries' market paragraph.

Digests built before the primary sources were picked from the news feed
on coverage, reaction, category and on_site (LEGACY_WEIGHTS); their
rows keep those inputs and have no event or size.

Like the scoring weights, the weights and thresholds below are proposals,
not a locked spec.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..storage import Warehouse

NEW_YORK = ZoneInfo("America/New_York")
CUTOFF = time(7, 0)                   # the digest day turns over here, NY time

# ---------------------------------------------------------------------------
# Story importance (provisional: tune here, not in logic)
# ---------------------------------------------------------------------------

IMPORTANCE_WEIGHTS: dict[str, float] = {
    "event": 0.40,
    "reaction": 0.25,
    "size": 0.20,
    "on_site": 0.15,
}
# How digests built from the news feed, before primary sources, were scored.
LEGACY_WEIGHTS: dict[str, float] = {
    "coverage": 0.45,
    "reaction": 0.25,
    "category": 0.15,
    "on_site": 0.15,
}


@dataclass(frozen=True)
class Period:
    """How one kind of digest is sized and where its inputs top out. A week
    has bigger moves than a day, and more outlets per headline, so it needs
    more of both for full marks."""

    name: str                # the mart key
    size: int                # stories kept
    coverage_full_at: int    # outlets, for the market headlines
    reaction_full_at: float  # absolute return over the period, for a stock
    market_full_at: float    # the same for the S&P 500
    context: int             # market headlines kept
    reserved: int = 0        # places kept for RESERVED_CATEGORIES stories


DAILY = Period("daily", size=10, coverage_full_at=8, reaction_full_at=0.10, market_full_at=0.02,
               context=5, reserved=2)
WEEKLY = Period("weekly", size=15, coverage_full_at=12, reaction_full_at=0.20, market_full_at=0.04,
                context=10)
PERIODS: dict[str, Period] = {p.name: p for p in (DAILY, WEEKLY)}

# A story needs this to be picked at all: a mid-sized event (an 8.01 press
# release, 0.3) at a company worth $100bn, or a small one at a mega-cap.
MIN_PICK_SCORE = 0.20
RESERVED_CATEGORIES = frozenset({"policy", "macro"})
# A reserved place goes only to a story that scores at least this, so a
# meeting notice can't take the place of real news.
RESERVED_MIN_SCORE = 0.30

# --- sources ----------------------------------------------------------------

PRIMARY_FEEDS = frozenset({"sec_8k", "fed", "bls", "sec_press", "ftc"})
CONTEXT_FEEDS = frozenset({"finnhub_general"})
MARKET = "S&P 500"  # move_ticker of a story whose reaction is the market's

# --- events -----------------------------------------------------------------

# 8-K items by how much they say on their own; a filing scores its best
# item. 1.01 and 5.02 depend on the release's words (item_event).
EVENT_ITEMS: dict[str, float] = {
    "1.03": 1.0,   # bankruptcy or receivership
    "4.02": 0.9,   # past financial statements no longer reliable
    "2.01": 0.8,   # acquisition or disposal completed
    "2.02": 0.7,   # results
    "2.05": 0.6,   # exit or disposal costs
    "2.06": 0.6,   # material impairment
    "3.01": 0.5,   # delisting notice or transfer
    "7.01": 0.3,   # Regulation FD (with a press release; without, routine)
    "8.01": 0.3,   # other events (the same)
    "2.03": 0.0,   # a new debt
    "3.02": 0.0,   # unregistered share sale
    "5.03": 0.0,   # bylaw or fiscal-year change
    "5.07": 0.0,   # shareholder vote results
}
DEAL_AGREEMENT = 0.9   # 1.01 whose release is a merger or acquisition
OTHER_AGREEMENT = 0.2  # 1.01 otherwise: mostly credit agreements
TOP_OFFICER = 0.6      # 5.02 naming the CEO or CFO
OTHER_OFFICER = 0.1    # 5.02 otherwise: a director, a pay plan
OTHER_ITEM = 0.2       # an item not listed
_TOP_OFFICER = re.compile(
    r"\b(?:ceo|cfo|chief executive(?: officer)?|chief financial(?: officer)?)\b", re.IGNORECASE)

# Items that are never news on their own. 9.01 is the exhibit list.
ROUTINE_ITEMS = frozenset({"5.07", "5.03", "3.02"})
FINANCING_ITEMS = frozenset({"1.01", "2.03"})  # a credit agreement and the debt it creates
PRESS_ITEMS = frozenset({"7.01", "8.01"})      # news only with a press release attached

# Agency releases: (pattern on the title, event), first match wins, then
# the feed's default.
AGENCY_EVENTS: dict[str, tuple[tuple[re.Pattern[str], float], ...]] = {
    "fed": (
        (re.compile(r"\bFOMC statement\b", re.IGNORECASE), 1.0),
        (re.compile(r"^Minutes of the Federal Open Market Committee\b", re.IGNORECASE), 0.8),
    ),
    "bls": (
        (re.compile(r"^(?:Consumer Price Index|The Employment Situation)\b"), 1.0),
        (re.compile(r"^Producer Price Index\b"), 0.8),
    ),
}
AGENCY_DEFAULTS: dict[str, float] = {"fed": 0.2, "bls": 0.4, "ftc": 0.4, "sec_press": 0.2}
# An FTC action against a named listed company: suing to block, an order,
# a settlement.
FTC_CHALLENGE = 0.8
_FTC_ACTION = re.compile(
    r"\b(?:sues?|suing|block\w*|challeng\w*|complaint|takes? action|orders?|settle\w*|consent"
    r"|prevent\w*|abandon\w*|resolv\w*)\b", re.IGNORECASE)
# An SEC final rule, or an action against a named listed company.
SEC_ACTION = 0.5
_SEC_RULE = re.compile(r"\b(?:adopts|final rules?|finalizes)\b", re.IGNORECASE)
_SEC_CHARGE = re.compile(r"\b(?:charge[sd]?|sues?|settle\w*|fine[sd]?|penalt\w*|fraud)\b", re.IGNORECASE)
# Releases about the whole economy, from an event of MARKET_EVENT: as big
# as any company's news, and the market's move is theirs.
FULL_SIZE_FEEDS = frozenset({"fed", "bls"})
MARKET_EVENT = 0.4
FEED_CATEGORIES: dict[str, str] = {"fed": "macro", "bls": "macro", "sec_press": "policy", "ftc": "policy"}

# Market cap ($) at which size starts adding, and the decades to full marks.
SIZE_FROM = 1e10
SIZE_DECADES = 2.0

# Two articles published within MERGE_WINDOW of each other are the same
# story when their headlines' shared words carry at least this share of
# their combined weight (IDF-weighted Jaccard), or the lower figure when
# they lead with the same stock. Leading with the same stock in the same
# category is enough on its own.
SAME_STORY = 0.4
SAME_STORY_SAME_STOCK = 0.2
MERGE_WINDOW = timedelta(hours=36)
MAX_STORY_TICKERS = 5

_AMOUNT = r"\$[\d.,]+ ?(?:[kmb]|thousand|million|billion)?"
_NOT_NEWS: dict[str, re.Pattern[str]] = {
    "routine": re.compile(
        "|".join(
            (
                # fund holdings: "X LLC Takes Position in Y", "Has $1.2 Million Stake in Y $Y"
                rf"\b(?:takes?|acquires?|initiates?|purchases?|buys|opens?) (?:a )?(?:new )?(?:{_AMOUNT} )?(?:position|stake) in\b",
                rf"\b(?:has|holds) {_AMOUNT} (?:stock )?(?:position|stake|holdings) in\b",
                rf"\b(?:invests|makes (?:a )?new (?:{_AMOUNT} )?investment) in\b",
                (
                    r"\b(?:increases|decreases|raises|lowers|reduces|trims|boosts|lifts|cuts|grows) "
                    r"(?:its )?(?:holdings|position|stake) in\b"
                ),
                r"\bshares (?:(?:of|in) .+ )?(?:bought|sold|purchased|acquired) by\b",
                r"\b(?:buys|sells|acquires|purchases|trims|boosts|raises|lowers|cuts) (?:[\d,]+ |new )?shares (?:of|in)\b",
                # insider and congressional trades: "CFO Sells 16,524 Shares", "RSU
                # Vesting", "Insider Sells $206,189 in Stock", "Rep. X Acquires Y Stock"
                r"\b(?:rsus?|10b5-1|form 4|restricted stock units?)\b",
                (
                    r"\b(?:director|ceo|cfo|coo|cmo|cto|officer|insider|evp|svp|rep\.|sen\.|senator)\b.*"
                    r"\b(?:sells|sold|buys|bought|purchases|acquires|exercises|donates|gifts|receives|unloads|cashes)\b.*"
                    r"\b(?:shares|stock|options)\b"
                ),
                rf"\b(?:sells|buys|acquires|purchases) {_AMOUNT} (?:in|of|worth of) (?:stock|shares)\b",
                # "Nancy Pelosi Congressional Trade on Jul. 24", "Donald Trump - Salesforce Inc. Trump Trade on Jun. 18"
                r"\b(?:congressional|trump) trade on\b",
                # analyst housekeeping: target moves and unchanged ratings
                r"\bprice target\b",
                r"\b(?:reiterates|maintains|reaffirms|keeps)\b.*\b(?:rating|overweight|underweight|outperform|buy|hold)\b",
                # investor-relations calendar: conferences, call dates, dividends
                r"\bto (?:present|participate|speak) at\b|\b(?:conference call|webcast)\b",
                r"\bto (?:report|announce|release)\b.*\bresults on\b|\bdeclares\b.*\bdividend\b",
                r"\bsets (?:the )?date\b",
                # templated price recaps: "X stock underperforms Tuesday when compared
                # to competitors", "X (Y) Stock Sinks As Market Gains: Key Facts"
                r"\bstock (?:under|out)performs (?:\w+ )?(?:when compared to )?competitors\b",
                (
                    r"\b(?:as|while|despite) (?:the )?(?:broader )?(?:stock )?market "
                    r"(?:gains|rises|climbs|dips|slips|falls|drops|declines|upswing|downturn|slip|dip)\b"
                ),
                r"\b(?:higher|lower) than (?:the )?(?:broader )?market\b",
                r"\b(?:laps|trails|beats|outpaces|lags) (?:the )?stock market\b",
                # "X stock hits 52-week low at 35.31 USD", "X stock may move 6.2% on
                # Sept. 10 earnings release": one template, a different stock each
                r"\bhits? (?:a )?(?:new )?52-week (?:high|low)\b",
                r"\bmay move [\d.]+% on\b",
                # law-firm solicitations: "Bronstein, Gewirtz & Grossman Urges X
                # Investors to Act", "Shareholder Alert", "Lead Plaintiff Deadline"
                r"\b(?:urges|reminds|encourages|alerts|notifies)\b.*\b(?:investors|shareholders)\b",
                r"\b(?:shareholder|investor)s? (?:alert|notice|reminder)\b|\blead plaintiff\b",
            )
        ),
        re.IGNORECASE,
    ),
    "commentary": re.compile(
        "|".join(
            (
                r"\?['\"’”]?\s*$",  # "Is X a Buy?", "Can It Deliver?"
                r"^(?:here'?s|here’s|prediction:|forget|should you|is it time|why i)\b",
                r"\b(?:jim )?cramer\b|\bfinal trades\b",
                r"\b(?:stocks?|shares) to (?:buy|watch|own|avoid|hold)\b",
                r"\bbetter (?:\w+ )?(?:stock|buy)\b",
            )
        ),
        re.IGNORECASE,
    ),
}

CATEGORIES: dict[str, re.Pattern[str]] = {
    "deal": re.compile(
        r"\b(?:acquir\w*|acquisition|mergers?|merge[sd]?|buyout|takeover|spin-?off|to buy|bid for)\b",
        re.IGNORECASE,
    ),
    "earnings": re.compile(
        r"\b(?:earnings|results|revenue|profit|guidance|outlook|eps|q[1-4])\b", re.IGNORECASE
    ),
    # Not "fed up". Not a bare "rate hike" either: that is as often a
    # utility's or a tax rate, and a Fed story also says "Fed" or "interest rate".
    "macro": re.compile(
        r"\b(?:fed(?! up\b)|federal reserve|fomc|powell|interest rates?|inflation|cpi|pce"
        r"|payrolls|jobs report|unemployment|gdp|recession|tariffs?|treasury yields?)\b",
        re.IGNORECASE,
    ),
    # Government action: regulators and prosecutors, Congress, the White
    # House, sanctions and export controls. Tariffs are macro.
    "policy": re.compile(
        "|".join(
            (
                # the SEC acting, not a company's filing with it ("Apple Inc. SEC
                # Filing (Aug 11, 2026)", "Files 10-Q with the U.S. SEC")
                (
                    r"(?<!files )(?<!with )(?<!with the )(?<!with u\.s\. )(?<!with the u\.s\. )"
                    r"\b(?:sec|securities and exchange commission)\b(?! (?:\d+-?[kq] )?(?:filings?|forms?|reports?)\b)"
                ),
                r"\b(?:ftc|federal trade commission|doj|justice department|department of justice|antitrust)\b",
                # Congress, not a medical one ("ESC Congress 2026"), Bill Ackman or
                # the tax bill on an executive's vested shares
                r"\bcongress(?= (?:pass|approv|vot|clear|reject|block|weigh|debat|stall|fail|probe|investigat))",
                r"\b(?:before|to|in) (?:the )?(?:u\.?s\.? )?congress\b(?! \d)",
                r"\bcongressional (?:hearing|probe|investigation|committee|panel|testimony|leaders?)\b",
                r"\b(?:senate|senators?|lawmakers?|legislation|legislators?|legislative|legislature)\b",
                r"\bhouse (?:bill|vote|passes|panel|committee|republicans|democrats|speaker|lawmakers)\b",
                r"\b(?:spending|funding|stopgap|appropriations|budget|house|senate) bills?\b",
                r"\b(?:passes|passed|signs|signed|vetoes|vetoed) (?:a |the )?(?:\w+ )?bill\b",
                # the White House, not Trump Media or his family's ventures
                r"\b(?:white house|executive orders?|oval office)\b",
                r"(?<!eric )\btrump\b(?!(?:'s|’s)? media|-backed|-linked| jr)",
                r"\b(?:sanction(?:s|ed|ing)?|entity list)\b",
                r"\bexport (?:controls?|curbs?|restrictions?|bans?|licen[cs]es?|rules?|limits?)\b",
            )
        ),
        re.IGNORECASE,
    ),
}

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "over",
        "says",
        "said",
        "than",
        "that",
        "the",
        "their",
        "this",
        "to",
        "up",
        "was",
        "were",
        "will",
        "with",
        "after",
        "amid",
        "new",
        "how",
        "why",
        "what",
    ]
)
# "$KIM", "(NASDAQ: TILE)": tags, not words of the headline
_TICKER_TAG = re.compile(r"\$[a-z.]+|\((?:nasdaq|nyse|amex|otc)[a-z]*\s*:\s*[a-z.]+\)")
_COUNTRY = re.compile(r"\b(?:canada|uk|india|australia|singapore)\b")
_DOMAIN = re.compile(r"\.(?:com|ca|co\.uk|co|net|org|in|au)\b")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Article:
    article_id: str
    published_at: datetime  # UTC, naive (as staged)
    source: str | None
    headline: str
    summary: str | None
    url: str
    tickers: tuple[str, ...]
    words: frozenset[str]
    categories: tuple[str, ...]
    feed: str | None = None
    items: tuple[str, ...] = ()  # an 8-K's item numbers


@dataclass(frozen=True)
class Story:
    articles: tuple[Article, ...]
    lead: Article
    tickers: tuple[str, ...]
    categories: tuple[str, ...]
    n_outlets: int
    move_ticker: str | None
    move_return: float | None
    inputs: dict[str, float]
    score: float


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def digest_window(digest_date: date) -> tuple[datetime, datetime]:
    """[start, end) of a daily digest, in naive UTC like published_at."""
    start = datetime.combine(previous_weekday(digest_date), CUTOFF, NEW_YORK)
    end = datetime.combine(digest_date, CUTOFF, NEW_YORK)
    return _utc(start), _utc(end)


def weekly_window(friday: date) -> tuple[datetime, datetime]:
    """[start, end) of the weekly digest dated `friday`, in naive UTC: the
    seven days to 07:00 New York time on the Saturday after it."""
    start = datetime.combine(friday - timedelta(days=6), CUTOFF, NEW_YORK)
    end = datetime.combine(friday + timedelta(days=1), CUTOFF, NEW_YORK)
    return _utc(start), _utc(end)


def week_sessions(friday: date) -> list[date]:
    """Monday to Friday of the week ending `friday`."""
    return [friday - timedelta(days=k) for k in range(4, -1, -1)]


def latest_weekly_date(now: datetime) -> date:
    """The Friday of the newest weekly digest whose window has closed: the
    one before the latest Saturday 07:00 New York time."""
    local = now.astimezone(NEW_YORK)
    saturday = local.date() - timedelta(days=(local.weekday() - 5) % 7)
    if saturday == local.date() and local.time() < CUTOFF:
        saturday -= timedelta(days=7)
    return saturday - timedelta(days=1)


def latest_digest_date(now: datetime) -> date:
    """The newest digest whose window has closed: today's from 07:00 NY time
    on a weekday, otherwise the weekday before."""
    local = now.astimezone(NEW_YORK)
    if local.weekday() < 5 and local.time() >= CUTOFF:
        return local.date()
    return previous_weekday(local.date())


def not_news(headline: str) -> str | None:
    """'routine' or 'commentary' when the headline is one of those, else None."""
    return next((kind for kind, pattern in _NOT_NEWS.items() if pattern.search(headline)), None)


def headline_words(headline: str) -> frozenset[str]:
    """Lower-cased content words, possessives and plurals folded."""
    text = _TICKER_TAG.sub(" ", headline.lower())
    text = re.sub(r"['’]s\b", "", text)
    words = set()
    for w in re.findall(r"[a-z0-9]+", text):
        if len(w) < 2 or w in _STOPWORDS:
            continue
        words.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return frozenset(words)


def word_weights(articles: list[Article]) -> dict[str, float]:
    """Inverse document frequency of each headline word across the window:
    a word in every other headline weighs little, a name in three weighs a
    lot."""
    df = Counter(w for a in articles for w in a.words)
    n = len(articles)
    return {w: math.log((1 + n) / (1 + k)) + 1 for w, k in df.items()}


def similarity(
    a: frozenset[str], b: frozenset[str], weights: dict[str, float] | None = None
) -> float:
    """Jaccard overlap of two headlines' words, IDF-weighted when given weights."""
    if not weights:
        union = len(a | b)
        return len(a & b) / union if union else 0.0
    weighted_union = sum(weights.get(w, 1.0) for w in a | b)
    return sum(weights.get(w, 1.0) for w in a & b) / weighted_union if weighted_union else 0.0


def outlet(source: str | None) -> str:
    """One key per outlet: 'Investing.com Canada' and 'Investing.com', or
    'www.marketscreener.com' and 'marketscreener.com', count once."""
    s = (source or "").lower().removeprefix("www.")
    s = _DOMAIN.sub(" ", _COUNTRY.sub(" ", s))
    return re.sub(r"[^a-z0-9]", "", s) or "unknown"


def categories_of(headline: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in CATEGORIES.items() if pattern.search(headline))


def routine_items(items: Iterable[str], released: bool | None = None) -> bool:
    """Whether an 8-K with these items is never news: exhibits only, a vote
    result, a bylaw change, an unregistered share sale, or a financing (a
    credit agreement with the debt it creates). With released=False (no
    press release attached), a Regulation FD or other-events item too;
    with `released` unknown, only what is routine either way."""
    rest = set(items) - {"9.01"}
    return (not rest or rest <= ROUTINE_ITEMS
            or ("2.03" in rest and rest <= FINANCING_ITEMS | ROUTINE_ITEMS)
            or (released is False and rest <= PRESS_ITEMS | ROUTINE_ITEMS))


def item_event(items: Iterable[str], text: str) -> float:
    """An 8-K's event: its best item's. `text` is the release's headline and
    summary, which say whether a material agreement is a deal and whether
    an officer change is the CEO or CFO."""
    def one(item: str) -> float:
        if item == "1.01":
            return DEAL_AGREEMENT if CATEGORIES["deal"].search(text) else OTHER_AGREEMENT
        if item == "5.02":
            return TOP_OFFICER if _TOP_OFFICER.search(text) else OTHER_OFFICER
        return EVENT_ITEMS.get(item, OTHER_ITEM)
    return max(map(one, set(items) - {"9.01"}), default=0.0)


def agency_event(feed: str, headline: str, tickers: tuple[str, ...] = ()) -> float:
    """An agency release's event, from its feed and title."""
    for pattern, event in AGENCY_EVENTS.get(feed, ()):
        if pattern.search(headline):
            return event
    if feed == "ftc" and tickers and _FTC_ACTION.search(headline):
        return FTC_CHALLENGE
    if feed == "sec_press" and (_SEC_RULE.search(headline) or (tickers and _SEC_CHARGE.search(headline))):
        return SEC_ACTION
    return AGENCY_DEFAULTS.get(feed, 0.0)


def article_event(a: Article) -> float:
    if a.feed == "sec_8k":
        return item_event(a.items, f"{a.headline} {a.summary or ''}")
    return agency_event(a.feed or "", a.headline, a.tickers)


def article_categories(headline: str, feed: str | None = None, items: Iterable[str] = (),
                       summary: str | None = None) -> tuple[str, ...]:
    """The headline's categories, plus what the source says: an agency's
    kind (macro or policy), an 8-K's results item (earnings) or completed
    or agreed deal."""
    cats = set(categories_of(headline))
    items = set(items)
    if feed in FEED_CATEGORIES:
        cats.add(FEED_CATEGORIES[feed])
    if "2.02" in items:
        cats.add("earnings")
    if "2.01" in items or ("1.01" in items and CATEGORIES["deal"].search(summary or "")):
        cats.add("deal")
    return tuple(name for name in CATEGORIES if name in cats)


def size_score(market_cap: float | None) -> float:
    """0 at a $10bn market cap, 1 at $1tn, on a log scale."""
    if not market_cap or market_cap <= 0:
        return 0.0
    return min(1.0, max(0.0, math.log10(market_cap / SIZE_FROM) / SIZE_DECADES))


def market_wide(a: Article, event: float) -> bool:
    """A Fed decision or a BLS figure: about the whole economy, so it counts
    as full size and the S&P 500's move is its reaction. Not the Fed's
    meeting schedules and discount-rate minutes."""
    return a.feed in FULL_SIZE_FEEDS and event >= MARKET_EVENT


def same_story(a: Article, b: Article, weights: dict[str, float]) -> bool:
    if abs(a.published_at - b.published_at) > MERGE_WINDOW:
        return False
    same_stock = bool(a.tickers and b.tickers and a.tickers[0] == b.tickers[0])
    if same_stock and set(a.categories) & set(b.categories):
        return True
    bar = SAME_STORY_SAME_STOCK if same_stock else SAME_STORY
    return similarity(a.words, b.words, weights) >= bar


def group_stories(articles: list[Article]) -> list[list[Article]]:
    """One pass, oldest first: each article joins the first story with a
    member it matches, or starts a new one. The order is fixed, so a rebuild
    over the same articles groups them the same way.

    A match needs a shared word or a shared lead stock, so each article is
    only checked against the stories indexed under one of its own."""
    weights = word_weights(articles)
    stories: list[list[Article]] = []
    index: dict[str, set[int]] = {}
    for article in sorted(articles, key=lambda a: (a.published_at, a.article_id)):
        keys = [*article.words, *(f"${t}" for t in article.tickers[:1])]
        candidates = sorted(set().union(*(index.get(k, ()) for k in keys)))
        home = next(
            (
                i
                for i in candidates
                if any(same_story(article, member, weights) for member in stories[i])
            ),
            None,
        )
        if home is None:
            home = len(stories)
            stories.append([])
        stories[home].append(article)
        for k in keys:
            index.setdefault(k, set()).add(home)
    return stories


def lead_article(articles: list[Article]) -> Article:
    """The member whose headline is most like the others', so it best stands
    for the story; ties go to one with a summary, then the earliest."""

    def key(a: Article) -> tuple:
        overlap = sum(similarity(a.words, b.words) for b in articles if b is not a)
        return (overlap, a.summary is not None, -a.published_at.timestamp())

    return max(articles, key=key)


def story_tickers(articles: list[Article]) -> tuple[str, ...]:
    """The stocks a story is about: each article's lead stock, plus any other
    that at least two articles and half of them name. A stock one article
    mentions in passing doesn't count, so its move can't lift the story."""
    leads = Counter(a.tickers[0] for a in articles if a.tickers)
    named = Counter(t for a in articles for t in a.tickers)
    keep = set(leads) | {t for t, n in named.items() if n >= 2 and 2 * n >= len(articles)}
    return tuple(sorted(keep, key=lambda t: (-leads[t], -named[t], t)))[:MAX_STORY_TICKERS]


def score_story(
    articles: list[Article], moves: dict[str, float], ranked: set[str], period: Period = DAILY,
    sizes: dict[str, float] | None = None, market: float | None = None,
) -> Story:
    """A primary-source story's score. `moves` are stock returns over the
    period, `sizes` market caps in dollars, `market` the S&P 500's return.

    The lead is the release with the biggest event (of those, the one most
    like the others); the story's event is the lead's."""
    events = {a.article_id: article_event(a) for a in articles}
    event = max(events.values())
    lead = lead_article([a for a in articles if events[a.article_id] == event])
    tickers = story_tickers(articles)
    cats = tuple(sorted({c for a in articles for c in a.categories}))
    n_outlets = len({outlet(a.source) for a in articles})
    whole = market_wide(lead, event)
    # Only the stock the story leads with: a co-named stock's move is not
    # this story's reaction. A Fed or BLS release's is the market's.
    move_ticker = move_return = None
    reaction = 0.0
    if tickers and tickers[0] in moves:
        move_ticker, move_return = tickers[0], moves[tickers[0]]
        reaction = min(1.0, abs(move_return) / period.reaction_full_at)
    elif not tickers and whole and market is not None:
        move_ticker, move_return = MARKET, market
        reaction = min(1.0, abs(market) / period.market_full_at)
    inputs = {
        "event": event,
        "reaction": reaction,
        "size": 1.0 if whole else size_score((sizes or {}).get(tickers[0])) if tickers else 0.0,
        "on_site": 1.0 if ranked.intersection(tickers) else 0.0,
    }
    score = sum(IMPORTANCE_WEIGHTS[k] * v for k, v in inputs.items())
    return Story(
        articles=tuple(sorted(articles, key=lambda a: a.published_at)),
        lead=lead,
        tickers=tickers,
        categories=cats,
        n_outlets=n_outlets,
        move_ticker=move_ticker,
        move_return=move_return,
        inputs=inputs,
        score=score,
    )


def _by_score(stories: list[Story]) -> list[Story]:
    """Highest score first; ties go to the story with more articles, then
    the more recent one."""
    return sorted(stories, key=lambda s: (-s.score, -len(s.articles),
                                          -s.lead.published_at.timestamp(), s.lead.article_id))


def rank_stories(
    groups: list[list[Article]], moves: dict[str, float], ranked: set[str], period: Period = DAILY,
    sizes: dict[str, float] | None = None, market: float | None = None,
) -> list[Story]:
    return _by_score([score_story(g, moves, ranked, period, sizes, market) for g in groups])


def score_context(articles: list[Article], period: Period = DAILY) -> Story:
    """A market headline's score: how many outlets ran it, full marks at
    the period's coverage_full_at."""
    n_outlets = len({outlet(a.source) for a in articles})
    coverage = min(1.0, math.log2(n_outlets) / math.log2(period.coverage_full_at))
    return Story(
        articles=tuple(sorted(articles, key=lambda a: a.published_at)),
        lead=lead_article(articles), tickers=story_tickers(articles),
        categories=tuple(sorted({c for a in articles for c in a.categories})), n_outlets=n_outlets,
        move_ticker=None, move_return=None, inputs={"coverage": coverage}, score=coverage,
    )


def pick_context(groups: list[list[Article]], period: Period = DAILY) -> list[Story]:
    """The period's most covered market headlines."""
    return _by_score([score_context(g, period) for g in groups])[:period.context]


def reserved_kind(story: Story) -> bool:
    """Policy or macro news, which a day keeps places for."""
    return not RESERVED_CATEGORIES.isdisjoint(story.categories)


def pick_stories(ranked: list[Story], period: Period = DAILY) -> list[Story]:
    """The period's top stories from `ranked` (best first) that score at
    least MIN_PICK_SCORE, keeping up to `period.reserved` places for policy
    and macro stories: when fewer make the top on score, the best of the
    rest scoring at least RESERVED_MIN_SCORE take the places of the
    lowest-ranked others. A reserved pick scored below every story it
    joins, so the picks stay in score order with it at the bottom."""
    ranked = [s for s in ranked if s.score >= MIN_PICK_SCORE]
    top = ranked[:period.size]
    missing = period.reserved - sum(map(reserved_kind, top))
    extra = [
        s for s in ranked[period.size :] if reserved_kind(s) and s.score >= RESERVED_MIN_SCORE
    ][: max(missing, 0)]
    if not extra:
        return top
    dropped = {s.lead.article_id for s in [s for s in top if not reserved_kind(s)][-len(extra) :]}
    return [s for s in top if s.lead.article_id not in dropped] + extra


# ---------------------------------------------------------------------------
# Warehouse IO
# ---------------------------------------------------------------------------

def _load_articles(con, start: datetime, end: datetime, feeds: frozenset[str]) -> list[Article]:
    rows = con.execute(
        """
        SELECT article_id, published_at, source, headline, summary, url, tickers, feed, items
        FROM staging.stg_news_articles
        WHERE published_at >= ? AND published_at < ? AND feed IN (SELECT UNNEST(?::VARCHAR[]))
        """,
        [start, end, sorted(feeds)],
    ).fetchall()
    return [
        Article(article_id=aid, published_at=ts, source=src, headline=h, summary=s,
                url=u, tickers=tuple(tk or ()), words=headline_words(h),
                categories=article_categories(h, feed, items or (), s),
                feed=feed, items=tuple(items or ()))
        for aid, ts, src, h, s, u, tk, feed, items in rows
    ]


def _moves(con, tickers: set[str], session_date: date, before: date) -> dict[str, float]:
    """Each stock's 1-day return on its latest session from session_date up
    to (not including) the digest date."""
    if not tickers:
        return {}
    rows = con.execute(
        """
        SELECT ticker, arg_max(return_1d, date)
        FROM staging.stg_prices_daily
        WHERE ticker IN (SELECT UNNEST(?::VARCHAR[]))
          AND date >= ? AND date < ? AND return_1d IS NOT NULL
        GROUP BY ticker
        """,
        [sorted(tickers), session_date, before],
    ).fetchall()
    return {t: r for t, r in rows}


def _week_moves(con, tickers: set[str], first: date, last: date) -> dict[str, float]:
    """Each stock's return over the sessions first..last, compounded from
    its 1-day returns."""
    if not tickers:
        return {}
    rows = con.execute(
        """
        SELECT ticker, exp(sum(ln(1 + return_1d))) - 1
        FROM staging.stg_prices_daily
        WHERE ticker IN (SELECT UNNEST(?::VARCHAR[]))
          AND date BETWEEN ? AND ? AND return_1d IS NOT NULL
        GROUP BY ticker
        """,
        [sorted(tickers), first, last],
    ).fetchall()
    return {t: r for t, r in rows}


def _market_day(con, session_date: date, before: date) -> tuple[float | None, float | None]:
    """The S&P 500's 1-day return and the VIX's close on their latest
    session from session_date up to (not including) the digest date."""
    return con.execute(
        """
        WITH spx AS (
            SELECT date, value / lag(value) OVER (ORDER BY date) - 1 AS r
            FROM staging.stg_fred_market WHERE series = 'SP500' AND value IS NOT NULL
        )
        SELECT (SELECT arg_max(r, date) FROM spx WHERE date >= ? AND date < ? AND r IS NOT NULL),
               (SELECT arg_max(value, date) FROM staging.stg_fred_market
                WHERE series = 'VIXCLS' AND value IS NOT NULL AND date >= ? AND date < ?)
        """,
        [session_date, before, session_date, before],
    ).fetchone()


def _market_week(con, first: date, last: date) -> tuple[float | None, float | None]:
    """The S&P 500's return over the sessions first..last (from the close
    before them) and the VIX's latest close in them."""
    return con.execute(
        """
        SELECT arg_max(value, date) FILTER (WHERE series = 'SP500' AND date BETWEEN ? AND ?)
                 / arg_max(value, date) FILTER (WHERE series = 'SP500' AND date < ?) - 1,
               arg_max(value, date) FILTER (WHERE series = 'VIXCLS' AND date BETWEEN ? AND ?)
        FROM staging.stg_fred_market
        WHERE series IN ('SP500', 'VIXCLS') AND value IS NOT NULL
        """,
        [first, last, first, first, last],
    ).fetchone()


def _sizes(con, tickers: set[str]) -> dict[str, float]:
    """Each stock's market cap in dollars (the profile has it in millions)."""
    if not tickers:
        return {}
    rows = con.execute(
        """
        SELECT ticker, max(TRY_CAST(json_extract_string(payload, '$.marketCapitalization') AS DOUBLE))
        FROM raw.raw_company_profile
        WHERE ticker IN (SELECT UNNEST(?::VARCHAR[]))
        GROUP BY ticker
        """,
        [sorted(tickers)],
    ).fetchall()
    return {t: cap * 1e6 for t, cap in rows if cap is not None}


def _ranked(con, digest_date: date) -> set[str]:
    """Stocks in the weekly and quarterly rankings published before `digest_date`."""
    rows = con.execute(
        """
        SELECT ticker FROM mart.weekly_rankings
        WHERE as_of = (SELECT MAX(as_of) FROM mart.weekly_rankings WHERE as_of < ?)
        UNION
        SELECT ticker FROM mart.model_rankings
        WHERE as_of = (SELECT MAX(as_of) FROM mart.model_rankings WHERE as_of < ?)
        """,
        [digest_date, digest_date],
    ).fetchall()
    return {t for (t,) in rows}


def _build(
    warehouse: Warehouse,
    period: Period,
    digest_date: date,
    window: tuple[datetime, datetime],
    moves: Callable[[Any, set[str]], dict[str, float]],
    market: Callable[[Any], tuple[float | None, float | None]],
    ranked_before: date,
) -> dict:
    """Pick one digest's stories and market headlines and replace its rows
    in all four digest tables; returns what was built.

    In the digest's row, articles, stories and outlets count the primary
    releases; routine_dropped and commentary_dropped the market headlines
    left out of the context."""
    start, end = window
    with warehouse.connect() as con:
        articles = _load_articles(con, start, end, PRIMARY_FEEDS)
        headlines = _load_articles(con, start, end, CONTEXT_FEEDS)
        kinds = Counter(not_news(a.headline) for a in headlines)
        context = pick_context(group_stories([a for a in headlines if not_news(a.headline) is None]),
                               period)
        groups = group_stories(articles)
        tickers = {t for a in articles for t in a.tickers}
        sp500, vix = market(con)
        stories = pick_stories(rank_stories(groups, moves(con, tickers), _ranked(con, ranked_before),
                                            period, _sizes(con, tickers), sp500), period)
        summary = {
            "period": period.name,
            "digest_date": digest_date.isoformat(),
            "articles": len(articles),
            "routine_dropped": kinds["routine"],
            "commentary_dropped": kinds["commentary"],
            "stories": len(groups),
            "outlets": len({outlet(a.source) for a in articles}),
            "picked": len(stories),
            "context": len(context),
            "sp500_return": sp500,
            "vix": vix,
        }

        key = [period.name, digest_date]
        con.execute("BEGIN TRANSACTION")
        for table in ("news_digests", "news_digest_stories", "news_digest_articles",
                      "news_digest_context"):
            con.execute(f"DELETE FROM mart.{table} WHERE period = ? AND digest_date = ?", key)
        con.execute(
            """
            INSERT INTO mart.news_digests (period, digest_date, window_start, window_end, articles,
                routine_dropped, commentary_dropped, stories, outlets, session_gap_minutes,
                sp500_return, vix, built_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            [*key, start, end, summary["articles"], summary["routine_dropped"],
             summary["commentary_dropped"], summary["stories"], summary["outlets"],
             sp500, vix, datetime.now(UTC)],
        )
        for rank, s in enumerate(stories, start=1):
            con.execute(
                """
                INSERT INTO mart.news_digest_stories (period, digest_date, rank, headline, summary,
                    url, source, published_at, tickers, categories, n_articles, n_outlets,
                    move_ticker, move_return, coverage, reaction, category, on_site, score,
                    event, size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?, ?, ?)
                """,
                [*key, rank, s.lead.headline, s.lead.summary, s.lead.url, s.lead.source,
                 s.lead.published_at, list(s.tickers), list(s.categories), len(s.articles),
                 s.n_outlets, s.move_ticker, s.move_return, s.inputs["reaction"],
                 s.inputs["on_site"], s.score, s.inputs["event"], s.inputs["size"]],
            )
            con.executemany(
                "INSERT INTO mart.news_digest_articles (period, digest_date, rank, article_id)"
                " VALUES (?, ?, ?, ?)",
                [[*key, rank, a.article_id] for a in s.articles],
            )
        if context:
            con.executemany(
                """
                INSERT INTO mart.news_digest_context (period, digest_date, rank, headline, summary,
                    url, source, published_at, n_articles, n_outlets, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [[*key, rank, c.lead.headline, c.lead.summary, c.lead.url, c.lead.source,
                  c.lead.published_at, len(c.articles), c.n_outlets, c.score]
                 for rank, c in enumerate(context, start=1)],
            )
        con.execute("COMMIT")
    return summary


def build_daily_digest(warehouse: Warehouse, digest_date: date) -> dict:
    """Rebuild one daily digest from the staged news. A story's reaction is
    its lead stock's move, or the market's, in the session before the
    digest date."""
    if digest_date.weekday() >= 5:
        raise ValueError(f"{digest_date} is a weekend; daily digests are dated Monday to Friday")
    session = previous_weekday(digest_date)
    return _build(
        warehouse, DAILY, digest_date, digest_window(digest_date),
        lambda con, tickers: _moves(con, tickers, session, digest_date),
        lambda con: _market_day(con, session, digest_date), digest_date,
    )


def build_weekly_digest(warehouse: Warehouse, friday: date) -> dict:
    """Rebuild the weekly digest dated `friday` from the staged news. A
    story's reaction is its lead stock's move, or the market's, over the
    week's sessions; the rankings published that Friday evening count as on
    the site."""
    if friday.weekday() != 4:
        raise ValueError(f"{friday} is not a Friday; weekly digests are dated by the week's Friday")
    sessions = week_sessions(friday)
    return _build(
        warehouse, WEEKLY, friday, weekly_window(friday),
        lambda con, tickers: _week_moves(con, tickers, sessions[0], sessions[-1]),
        lambda con: _market_week(con, sessions[0], sessions[-1]), friday + timedelta(days=1),
    )


def build_daily_digests(warehouse: Warehouse, last: date, days: int = 1) -> list[dict]:
    """The digest dated `last` and the `days - 1` weekdays before it, oldest
    first: a backfill when the archive should reach further back."""
    dates = [last]
    while len(dates) < days:
        dates.append(previous_weekday(dates[-1]))
    return [build_daily_digest(warehouse, d) for d in reversed(dates)]


def build_weekly_digests(warehouse: Warehouse, last: date, weeks: int = 1) -> list[dict]:
    """The weekly digest dated Friday `last` and the `weeks - 1` before it,
    oldest first."""
    fridays = [last - timedelta(weeks=k) for k in range(max(weeks, 1) - 1, -1, -1)]
    return [build_weekly_digest(warehouse, f) for f in fridays]
