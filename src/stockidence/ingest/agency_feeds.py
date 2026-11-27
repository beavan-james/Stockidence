"""Macro and policy stories from government releases.

Registry: agency_releases (endpoints.py has the cadence, watermark and TTL).

FEEDS: the Federal Reserve's monetary-policy releases (FOMC statements and
minutes), BLS's headline numbers, SEC press releases and the FTC's
competition releases. Each site's robots.txt is read with the scraper's
rules (ingest.articles) before its feed is requested; a feed whose site
shuts the scraper or the AI crawlers out is skipped, and so is a feed that
fails, without failing the others.

BLS has one feed for its headline numbers: each indicator with its latest
figure, the period it covers and a link to its news release. A new release
is a figure for a new period, so there is one article per (release,
period), the indicators sharing a release (the jobs report's unemployment
rate, payrolls and hourly earnings) folded into one. The first run lands
the figures already out undated, so they are known and never news.

Few releases name companies. An SEC or FTC release whose title names a
tracked company gets its tickers, so the stock's move and size count.

Three steps, as in ingest.articles: plan (read the warehouse), fetch
(network only, no connection open), land.
"""

from __future__ import annotations

import email.utils
import html as html_lib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..storage import Warehouse
from .articles import ALLOWED, ArticleFetcher
from .clients.base import APIError, InvalidResponseError, RateLimitError
from .raw_mapping import article_id, primary_news_rows

ATOM = "{http://www.w3.org/2005/Atom}"
PROVIDER = "agencies"
# a release older than this is not landed: a week's digest, plus a day
LOOKBACK = timedelta(days=8)
MAX_SUMMARY = 600


@dataclass(frozen=True)
class Feed:
    key: str      # stg_news_articles.feed
    source: str   # stg_news_articles.source
    url: str


FEEDS: tuple[Feed, ...] = (
    Feed("fed", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    Feed("bls", "BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    Feed("sec_press", "SEC", "https://www.sec.gov/news/pressreleases.rss"),
    Feed("ftc", "FTC", "https://www.ftc.gov/feeds/press-release-competition.xml"),
)
AGENCY_FEEDS = frozenset(f.key for f in FEEDS)
# feeds whose titles are matched against the tracked companies' names
NAMED_FEEDS = frozenset({"sec_press", "ftc"})

# BLS news releases by the code in their link (news.release/<code>.toc.htm)
BLS_RELEASES: dict[str, str] = {
    "cpi": "Consumer Price Index",
    "empsit": "The Employment Situation",
    "ppi": "Producer Price Index",
    "eci": "Employment Cost Index",
    "prod2": "Productivity and Costs",
    "ximpim": "Import and Export Price Indexes",
}

# Company names that are also everyday words: a title saying "Block" or
# "Target" is not taken to name the company.
_COMMON_NAMES = frozenset([
    "block", "target", "match", "ball", "gap", "progressive", "southern", "republic", "public",
    "global", "general", "united", "american", "first", "national", "international", "equity",
    "realty", "energy", "capital", "financial", "service", "services", "resources", "technologies",
    "systems", "partners", "brands", "health", "healthcare", "insurance"
])
_SUFFIX = re.compile(
    r"(?:[,.]?\s+(?:inc|incorporated|corp|corporation|co|company|companies|holdings?|group|ltd|limited"
    r"|plc|n\.?v|s\.?a|ag|se|lp|llc|l\.?p|trust|the|class [a-z]|/[a-z]{2}/?))+\.?$", re.IGNORECASE)


@dataclass(frozen=True)
class AgencyPlan:
    known: frozenset[str]                      # article ids already landed
    bls_seen: bool                             # a BLS release was landed before
    names: tuple[tuple[re.Pattern[str], str], ...]  # (name pattern, ticker)


@dataclass
class Pulled:
    articles: list[dict[str, Any]] = field(default_factory=list)
    feeds: dict[str, str] = field(default_factory=dict)  # feed -> outcome
    requests: int = 0


# --- names ------------------------------------------------------------------

def short_name(name: str) -> str:
    """'NVIDIA Corp' -> 'NVIDIA', 'The Kroger Co.' -> 'Kroger'."""
    name = re.sub(r"^the\s+", "", " ".join(name.split()), flags=re.IGNORECASE)
    while True:
        cut = _SUFFIX.sub("", name).strip(" ,.")
        if cut == name or not cut:
            return name
        name = cut


def name_patterns(companies: list[tuple[str, str]]) -> tuple[tuple[re.Pattern[str], str], ...]:
    """A whole-word pattern per company name that is safe to look for in a
    title: at least four letters, and not an everyday word on its own."""
    out = []
    for ticker, name in companies:
        short = short_name(name or "")
        if len(short) < 4 or short.lower() in _COMMON_NAMES:
            continue
        out.append((re.compile(rf"(?<![\w&]){re.escape(short)}(?:['’]s)?(?![\w&])", re.IGNORECASE), ticker))
    return tuple(out)


def named_tickers(title: str, names: tuple[tuple[re.Pattern[str], str], ...]) -> list[str]:
    return list(dict.fromkeys(t for pattern, t in names if pattern.search(title)))


# --- parsing ----------------------------------------------------------------

def _text(value: str | None) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _cap(text: str, limit: int = MAX_SUMMARY) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def parse_items(xml: bytes | str) -> list[dict[str, Any]]:
    """title, link, published (UTC), description of each RSS or Atom item."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    items = []
    for it in root.findall(".//item"):
        items.append({"title": _text(it.findtext("title")), "link": (it.findtext("link") or "").strip(),
                      "published": _when(it.findtext("pubDate")), "description": it.findtext("description")})
    for it in root.findall(f".//{ATOM}entry"):
        link = it.find(f"{ATOM}link")
        items.append({"title": _text(it.findtext(f"{ATOM}title")),
                      "link": (link.get("href", "") if link is not None else "").strip(),
                      "published": _when(it.findtext(f"{ATOM}updated")),
                      "description": it.findtext(f"{ATOM}summary")})
    return [i for i in items if i["title"] and i["link"]]


def bls_releases(description: str) -> list[dict[str, Any]]:
    """The latest-numbers item: one entry per news release and period, with
    the indicators it covers ((name, figure) pairs)."""
    releases: dict[tuple[str, str], dict[str, Any]] = {}
    for block in re.findall(r"<p>(.*?)</p>", description or "", re.DOTALL):
        name = re.match(r"\s*([^<]+?):\s*<br", block)
        figure = re.search(r'class="data"[^>]*>(.*?)</span>', block, re.DOTALL)
        link = re.search(r'href="(https?://[^"]*/news\.release/([a-z0-9]+)\.[a-z0-9]+\.htm)"', block)
        if not (name and figure and link):
            continue
        value, _, period = _text(figure.group(1)).rpartition(" in ")
        if not value or not period:
            continue
        code = link.group(2)
        url = link.group(1).replace(".toc.htm", ".nr0.htm")
        entry = releases.setdefault((url, period), {"url": url, "period": period, "code": code,
                                                    "indicators": []})
        entry["indicators"].append((_text(name.group(1)), value))
    return list(releases.values())


def bls_headline(release: dict[str, Any]) -> str:
    name = BLS_RELEASES.get(release["code"])
    indicators = release["indicators"]
    if len(indicators) == 1 and not name:
        n, v = indicators[0]
        return f"{n}: {v} in {release['period']}"
    figures = "; ".join(f"{n} {v}" for n, v in indicators)
    return f"{name or indicators[0][0]}, {release['period']}: {figures}"


# --- plan -------------------------------------------------------------------

def plan(warehouse: Warehouse) -> AgencyPlan:
    with warehouse.connect(read_only=True) as con:
        known = con.execute(
            """
            SELECT article_id, json_extract_string(payload, '$.feed') FROM raw.raw_news_articles
            WHERE json_extract_string(payload, '$.provider') = ?
            """,
            [PROVIDER],
        ).fetchall()
        companies = con.execute(
            """
            SELECT DISTINCT t.ticker, json_extract_string(p.payload, '$.name')
            FROM (SELECT DISTINCT ticker FROM staging.stg_prices_daily) t
            JOIN raw.raw_company_profile p USING (ticker)
            WHERE json_extract_string(p.payload, '$.name') IS NOT NULL
            ORDER BY 1
            """
        ).fetchall()
    return AgencyPlan(
        known=frozenset(a for a, _ in known),
        bls_seen=any(f == "bls" for _, f in known),
        names=name_patterns(companies),
    )


# --- fetch ------------------------------------------------------------------

def _payload(feed: Feed, key: str, title: str, url: str, published: datetime | None,
             summary: str | None, tickers: list[str], **extra: Any) -> dict[str, Any]:
    payload = {
        "article_id": article_id(key),
        "provider": PROVIDER,
        "feed": feed.key,
        "title": title,
        "ticker_sentiment": [{"ticker": t} for t in tickers],
        "source": feed.source,
        "summary": summary or None,
        "url": url,
        **extra,
    }
    if published is not None:
        payload["time_published"] = published.strftime("%Y%m%dT%H%M%S")
    return payload


def articles_from(feed: Feed, body: bytes | str, p: AgencyPlan, now: datetime) -> list[dict[str, Any]]:
    """The feed's new releases as article payloads."""
    out = []
    for item in parse_items(body):
        if feed.key == "bls":
            for release in bls_releases(item["description"]):
                key = f"{release['url']}#{release['period']}"
                if article_id(key) in p.known:
                    continue
                # first run: the figures already out are landed undated, so
                # staging leaves them out and later runs know them
                baseline = not p.bls_seen
                out.append(_payload(
                    feed, key, bls_headline(release), release["url"],
                    None if baseline else item["published"] or now, None, [],
                    period=release["period"], **({"baseline": True} if baseline else {})))
            continue
        published = item["published"]
        if published is None or now - published > LOOKBACK or article_id(item["link"]) in p.known:
            continue
        summary = _text(item["description"])
        if summary.rstrip(". ") == item["title"].rstrip(". ") or summary.startswith(item["title"][:60]):
            summary = ""  # the Fed's descriptions repeat the title
        tickers = named_tickers(item["title"], p.names) if feed.key in NAMED_FEEDS else []
        out.append(_payload(feed, item["link"], item["title"], item["link"], published,
                            _cap(summary), tickers))
    return out


def fetch(client: Any, p: AgencyPlan, now: datetime,
          verdict: Callable[[str], str], feeds: tuple[Feed, ...] = FEEDS) -> Pulled:
    """Read each feed whose site's robots.txt allows it; network only."""
    out = Pulled()
    for feed in feeds:
        allowed = verdict(feed.url)
        if allowed != ALLOWED:
            out.feeds[feed.key] = f"skipped ({allowed})"
            continue
        try:
            body = client.feed(feed.url)
            out.requests += 1
            new = articles_from(feed, body, p, now)
        except (APIError, InvalidResponseError, RateLimitError, httpx.HTTPError, ET.ParseError) as exc:
            out.feeds[feed.key] = f"failed ({type(exc).__name__})"
            continue
        out.articles.extend(new)
        out.feeds[feed.key] = f"{len(new)} new"
    return out


# --- land -------------------------------------------------------------------

def land(warehouse: Warehouse, pulled: Pulled, now: datetime) -> int:
    written = 0
    for artifact, rows in primary_news_rows(pulled.articles).items():
        if rows:
            written += warehouse.land(artifact, rows, fetched_at=now)
    return written


def pull_agency_releases(warehouse: Warehouse, client: Any | None = None, *,
                         now: datetime | None = None, fetcher: ArticleFetcher | None = None,
                         feeds: tuple[Feed, ...] = FEEDS) -> dict:
    """Plan, fetch and land the agencies' new releases; returns what
    happened, for the run log."""
    now = now or datetime.now(UTC)
    p = plan(warehouse)
    own_fetcher = fetcher is None
    fetcher = fetcher or ArticleFetcher()
    if client is None:
        from .clients.agencies import AgencyFeedClient

        client = AgencyFeedClient()
    try:
        pulled = fetch(client, p, now, fetcher.verdict, feeds)
    finally:
        if own_fetcher:
            fetcher.close()
    land(warehouse, pulled, now)
    return {"landed": len(pulled.articles), "feeds": pulled.feeds, "requests": pulled.requests,
            "baseline": sum(bool(a.get("baseline")) for a in pulled.articles)}
