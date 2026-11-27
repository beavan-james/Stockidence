"""Article pages behind the news digest's stories.

Registry: news_article.page (cadence event, watermark url, retry TTL 6h).
Not a provider API: these are the publisher pages the news feed links to,
fetched inside the digest jobs for the stories a digest picked, so the
summaries can be written from the article and not the feed's one-line
summary. NEWS_SUMMARIES.md is the spec. The rules:

- an honest user agent (SEC_USER_AGENT on sec.gov, whose fair-access
  rules ask for a name and contact), and robots.txt is obeyed as RFC
  9309 reads it
- a domain whose robots.txt shuts out the named AI crawlers is skipped
- a 403, a paywall or a bot check is never worked around
- one request at a time, with a gap between requests to the same domain
- per story, articles are tried lead first; the first with MIN_WORDS words
  wins, and at most TRIES_PER_STORY pages are requested
- a success is never fetched again; a transient failure is retried after
  RETRY_AFTER, at most MAX_ATTEMPTS times; anything else is final

Three steps: plan (read the warehouse), fetch (network only, no
connection open), land (write raw.news_article_pages).
"""

from __future__ import annotations

import re
import string
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, urlsplit

import httpx

from ..staging.article_text import extract_text
from ..storage import Warehouse

PRODUCT_TOKEN = "StockidenceBot"  # the name robots.txt groups know us by
USER_AGENT = f"{PRODUCT_TOKEN}/0.1 (news digest summaries)"
# Hosts whose own access rules name the user agent to send: SEC asks for a
# name and contact email (SEC_USER_AGENT), and limits requests per second.
SEC_HOSTS = frozenset({"www.sec.gov", "sec.gov", "data.sec.gov"})
# Crawlers that collect text for AI models. A site that disallows any of
# them for a URL has opted out of its text being read by one.
AI_CRAWLERS = ("ClaudeBot", "anthropic-ai", "GPTBot", "CCBot", "Google-Extended")

TIMEOUT = 15.0
SAME_DOMAIN_GAP = 2.0  # seconds between requests to one domain
MAX_BYTES = 5_000_000
MIN_WORDS = 150
TRIES_PER_STORY = 3
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(hours=6)
MAX_REQUESTS = 60  # page requests per run, a cap for backfills
# robots.txt is plain text. IIS answers the pages' HTML-only Accept with a
# 406, which would read as "no rules".
ROBOTS_ACCEPT = "text/plain, */*"

# robots.txt verdicts, stored in raw.news_article_pages.robots
ALLOWED = "allowed"
DISALLOWED = "disallowed"
AI_OPTOUT = "ai_optout"
UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class Page:
    """One fetch attempt for one URL, as landed in raw.news_article_pages."""

    url: str
    domain: str
    robots: str
    requested: bool = False  # whether the page itself was requested
    http_status: int | None = None
    final_url: str | None = None
    html: str | None = None
    error: str | None = None
    words: int = 0  # extracted words, for the stop rule; staging keeps the text

    @property
    def readable(self) -> bool:
        return self.words >= MIN_WORDS

    @property
    def outcome(self) -> str:
        """One word for the run log."""
        if self.readable:
            return "readable"
        if self.robots != ALLOWED:
            return self.robots
        if self.html is not None:
            return "thin"
        if self.http_status and self.http_status != 200:
            return f"http_{self.http_status}"
        return "error"  # no response, not HTML, or too big


def retryable(robots: str, http_status: int | None, has_html: bool) -> bool:
    """Whether a failed attempt may work later: a timeout or dropped
    connection, a 429 or 5xx, or a robots.txt that couldn't be read. A
    refusal (403 and other 4xx), a robots.txt block, or a page that came
    back without enough text is final."""
    if has_html:
        return False
    if robots == UNREACHABLE:
        return True
    if robots != ALLOWED:
        return False
    return http_status is None or http_status == 429 or http_status >= 500


def user_agent_for(host: str) -> str:
    """The user agent to send to `host`: SEC_USER_AGENT for sec.gov when it
    is set, the scraper's own otherwise. robots.txt is always read for
    USER_AGENT, the name the scraper goes by."""
    if host.lower() in SEC_HOSTS:
        from ..config import load_settings

        agent = load_settings().sec_user_agent
        if agent:
            return agent
    return USER_AGENT


def new_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


# --- robots.txt -------------------------------------------------------------

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_PRINTABLE = "".join(map(chr, range(0x21, 0x7F)))  # ASCII without space or controls


def _canonical(path: str) -> str:
    """One spelling for a path, so a rule and a URL compare octet by octet:
    non-ASCII and spaces percent-encoded, escaped unreserved characters
    decoded, other escapes upper-cased (RFC 9309 section 2.2.2)."""

    def unescape(m: re.Match[str]) -> str:
        char = chr(int(m[0][1:], 16))
        return char if char in _UNRESERVED else m[0].upper()

    return re.sub(r"%[0-9A-Fa-f]{2}", unescape, quote(path, safe=_PRINTABLE))


def _matches(pattern: str, path: str) -> bool:
    """Whether path starts with pattern, where * matches any run of
    characters and a final $ matches the end of the path. Tracks every
    place in the path the pattern so far can end at, so a pattern full of
    * can't make it backtrack."""
    ends = [0]
    for i, char in enumerate(pattern):
        if char == "$" and i == len(pattern) - 1:
            return ends[-1] == len(path)
        if char == "*":
            ends = list(range(ends[0], len(path) + 1))
        else:
            ends = [end + 1 for end in ends if path.startswith(char, end)]
            if not ends:
                return False
    return True


def _product_token(value: str) -> str:
    """The crawler a user-agent line names: * or its leading letters, - and
    _ (so Googlebot/2.1 names googlebot), lower-cased."""
    if value.startswith("*"):
        return "*"
    match = re.match(r"[A-Za-z_-]*", value)
    return match[0].lower() if match else ""


class Robots:
    """A robots.txt, read as RFC 9309 says.

    A crawler obeys every group that names its product token (in any case),
    combined, or else the * group. Of those rules, the longest one that
    matches the URL's path wins, and Allow wins a tie. A path no rule
    matches is allowed.
    """

    def __init__(self, text: str = "") -> None:
        self.groups: dict[str, list[tuple[bool, str]]] = {}  # crawler -> [(allow, pattern)]
        agents: list[str] = []
        in_rules = False  # a user-agent line after a rule starts a new group
        for line in text.removeprefix("\ufeff").splitlines():
            key, _, value = line.split("#", 1)[0].partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                if in_rules:
                    agents, in_rules = [], False
                agents.append(_product_token(value))
                self.groups.setdefault(agents[-1], [])
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                if value:  # an empty Disallow blocks nothing
                    for agent in agents:
                        self.groups[agent].append((key == "allow", _canonical(value)))

    def allows(self, agent: str, path: str) -> bool:
        """Whether the crawler with this product token may fetch path (the
        URL's path and query)."""
        rules = self.groups.get(agent.lower(), self.groups.get("*", []))
        path = _canonical(path)
        matched = [(len(pattern), allow) for allow, pattern in rules if _matches(pattern, path)]
        return max(matched)[1] if matched else True


NO_RULES = Robots()
KEEP_OUT = Robots("User-agent: *\nDisallow: /")


class ArticleFetcher:
    """Fetches pages politely: robots.txt first (once per domain per run),
    one request at a time, SAME_DOMAIN_GAP seconds between requests to a
    domain."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client or new_client()
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, Robots | None] = {}
        self._last: dict[str, float] = {}
        self.page_requests = 0

    def close(self) -> None:
        self.client.close()

    def _agent(self, host: str) -> dict[str, str]:
        """The User-Agent header for `host`, when it isn't the client's own."""
        agent = user_agent_for(host)
        return {} if agent == USER_AGENT else {"User-Agent": agent}

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            gap = SAME_DOMAIN_GAP - (self._clock() - last)
            if gap > 0:
                self._sleep(gap)

    def _robots_for(self, scheme: str, host: str) -> Robots | None:
        """The domain's robots.txt; None when it couldn't be read.

        401/403 means keep out; any other 4xx means there are no rules; a
        5xx or a failed request means try again later.
        """
        key = f"{scheme}://{host}"
        if key in self._robots:
            return self._robots[key]
        robots: Robots | None = None  # stays None on a 5xx or a failed request
        self._wait(host)
        try:
            resp = self.client.get(f"{key}/robots.txt",
                                   headers={"Accept": ROBOTS_ACCEPT, **self._agent(host)})
            if resp.status_code in (401, 403):
                robots = KEEP_OUT
            elif 400 <= resp.status_code < 500:
                robots = NO_RULES
            elif resp.status_code == 200:
                robots = Robots(resp.text)
        except httpx.HTTPError:
            pass
        finally:
            self._last[host] = self._clock()
        self._robots[key] = robots
        return robots

    def verdict(self, url: str) -> str:
        """What robots.txt says about reading this URL."""
        parts = urlsplit(url)
        robots = self._robots_for(parts.scheme or "https", parts.netloc.lower())
        if robots is None:
            return UNREACHABLE
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if not robots.allows(PRODUCT_TOKEN, path):
            return DISALLOWED
        if any(not robots.allows(bot, path) for bot in AI_CRAWLERS):
            return AI_OPTOUT
        return ALLOWED

    def fetch(self, url: str) -> Page:
        host = urlsplit(url).netloc.lower()
        verdict = self.verdict(url)
        if verdict != ALLOWED:
            return Page(url, host, verdict)
        self.page_requests += 1
        try:
            status, final_url, html, error = self._download(host, url)
        except httpx.HTTPError as exc:
            return Page(
                url, host, ALLOWED, requested=True, error=f"{type(exc).__name__}: {exc}"[:300]
            )
        page = Page(url, host, ALLOWED, True, status, final_url, html, error)
        if html is None:
            return page
        # A redirect to another domain is held to that domain's robots.txt.
        final_host = urlsplit(final_url).netloc.lower()
        if final_host != host:
            elsewhere = self.verdict(final_url)
            if elsewhere != ALLOWED:
                return replace(
                    page, robots=elsewhere, html=None, error=f"redirected to {final_host}"
                )
        return replace(page, words=extract_text(html, final_url).words)

    def _download(self, host: str, url: str) -> tuple[int, str, str | None, str | None]:
        """(status, final URL, html, error) for one page request."""
        self._wait(host)
        try:
            with self.client.stream("GET", url, headers=self._agent(host)) as resp:
                status, final_url = resp.status_code, str(resp.url)
                if status != 200:
                    return status, final_url, None, f"HTTP {status}"
                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return (
                        status,
                        final_url,
                        None,
                        f"not HTML ({content_type or 'no content type'})",
                    )
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        return status, final_url, None, f"page over {MAX_BYTES // 1_000_000} MB"
                return (
                    status,
                    final_url,
                    body.decode(resp.charset_encoding or "utf-8", "replace"),
                    None,
                )
        finally:
            self._last[host] = self._clock()


# --- plan -------------------------------------------------------------------


@dataclass(frozen=True)
class StoryLinks:
    """A picked story with no readable article yet, and the URLs to try."""

    period: str
    digest_date: date
    rank: int
    urls: tuple[str, ...]  # lead first, then the rest earliest first


def digests_to_read(built: Iterable[dict]) -> list[tuple[str, date]]:
    """The digests whose stories get read: each digest just built and, for
    a week, that week's daily digests too (Monday to Friday), since the
    weekly article covers every story the week's dailies picked."""
    keys: list[tuple[str, date]] = []
    for d in built:
        day = date.fromisoformat(str(d["digest_date"]))
        keys.append((d["period"], day))
        if d["period"] == "weekly":
            keys += [("daily", day - timedelta(days=k)) for k in range(4, -1, -1)]
    return list(dict.fromkeys(keys))


def _due(
    robots: str | None,
    http_status: int | None,
    has_html: bool,
    attempts: int | None,
    waited: bool | None,
) -> bool:
    if robots is None:  # never tried
        return True
    return (
        (attempts or 0) < MAX_ATTEMPTS and bool(waited) and retryable(robots, http_status, has_html)
    )


def plan(
    warehouse: Warehouse, digests: Iterable[tuple[str, date]], now: datetime
) -> list[StoryLinks]:
    """Each picked story still without readable text, with the URLs worth
    trying now. A URL in two digests (a story picked on Tuesday and again
    for the week) is planned once."""
    keys = [f"{period}|{day.isoformat()}" for period, day in digests]
    if not keys:
        return []
    with warehouse.connect(read_only=True) as con:
        rows = con.execute(
            """
            SELECT s.period, s.digest_date, s.rank, n.url,
                   t.words, p.robots, p.http_status, p.html IS NOT NULL, p.attempts,
                   p.last_tried_at <= ? AS waited
            FROM mart.news_digest_stories s
            JOIN mart.news_digest_articles a USING (period, digest_date, rank)
            JOIN staging.stg_news_articles n USING (article_id)
            LEFT JOIN raw.news_article_pages p ON p.url = n.url
            LEFT JOIN staging.stg_news_article_text t ON t.url = n.url
            WHERE list_contains(?, s.period || '|' || strftime(s.digest_date, '%Y-%m-%d'))
              AND n.url LIKE 'http%'
            ORDER BY s.period, s.digest_date, s.rank, n.url <> s.url, n.published_at, n.article_id
            """,
            [now - RETRY_AFTER, keys],
        ).fetchall()

    stories: dict[tuple[str, date, int], list[tuple]] = {}
    for period, day, rank, *link in rows:
        stories.setdefault((period, day, rank), []).append(tuple(link))

    planned: list[StoryLinks] = []
    seen: set[str] = set()
    for (period, day, rank), links in stories.items():
        if any((words or 0) >= MIN_WORDS for _, words, *_ in links):
            continue
        urls = []
        for url, _, robots, status, has_html, attempts, waited in links:
            if url in seen:
                continue
            seen.add(url)
            if _due(robots, status, has_html, attempts, waited):
                urls.append(url)
        if urls:
            planned.append(StoryLinks(period, day, rank, tuple(urls)))
    return planned


# --- fetch and land ---------------------------------------------------------


def fetch_stories(
    fetcher: ArticleFetcher, stories: Iterable[StoryLinks], max_requests: int = MAX_REQUESTS
) -> list[Page]:
    """Try each story's URLs in order until one is readable, requesting at
    most TRIES_PER_STORY pages per story and max_requests in all."""
    pages: list[Page] = []
    for story in stories:
        tries = 0
        for url in story.urls:
            if tries == TRIES_PER_STORY or fetcher.page_requests >= max_requests:
                break
            page = fetcher.fetch(url)
            pages.append(page)
            tries += page.requested
            if page.readable:
                break
        if fetcher.page_requests >= max_requests:
            break
    return pages


def land_pages(warehouse: Warehouse, pages: list[Page], now: datetime) -> int:
    """Upsert one row per URL; a retry updates the row and counts the attempt."""
    if not pages:
        return 0
    with warehouse.connect() as con:
        con.executemany(
            """
            INSERT INTO raw.news_article_pages (url, domain, robots, http_status, final_url,
                html, error, attempts, first_tried_at, last_tried_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT (url) DO UPDATE SET
                robots = excluded.robots, http_status = excluded.http_status,
                final_url = excluded.final_url, html = excluded.html, error = excluded.error,
                attempts = news_article_pages.attempts + 1, last_tried_at = excluded.last_tried_at
            """,
            [
                [p.url, p.domain, p.robots, p.http_status, p.final_url, p.html, p.error, now, now]
                for p in pages
            ],
        )
    return len(pages)


def fetch_digest_articles(
    warehouse: Warehouse,
    digests: Iterable[tuple[str, date]],
    *,
    now: datetime | None = None,
    fetcher: ArticleFetcher | None = None,
    max_requests: int = MAX_REQUESTS,
) -> dict:
    """Plan, fetch and land the pages for these digests' stories; returns
    what happened, for the run log."""
    now = now or datetime.now(UTC)
    stories = plan(warehouse, digests, now)
    own = fetcher is None
    fetcher = fetcher or ArticleFetcher()
    try:
        pages = fetch_stories(fetcher, stories, max_requests)
    finally:
        if own:
            fetcher.close()
    land_pages(warehouse, pages, now)
    readable = {p.url for p in pages if p.readable}
    return {
        "stories": len(stories),
        "stories_read": sum(any(u in readable for u in s.urls) for s in stories),
        "page_requests": fetcher.page_requests,
        "capped": fetcher.page_requests >= max_requests,
        "outcomes": dict(Counter(p.outcome for p in pages)),
        "skipped_domains": sorted({p.domain for p in pages if p.robots != ALLOWED}),
    }
