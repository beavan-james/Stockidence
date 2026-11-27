"""Company stories from SEC filings: the 8-Ks the tracked companies file.

Registry: sec_8k_releases and sec_company_tickers (endpoints.py has the
cadence, watermark and TTL of each). The news digest's company stories come
from here, not from a news feed: an 8-K is the company's own account of
the event, and EDGAR serves it to any client that names itself
(SEC_USER_AGENT), at most 10 requests a second.

Three steps, as in ingest.articles: plan (read the warehouse), fetch
(network only, no connection open), land.

Discovery: EDGAR's latest-filings Atom feed, newest first, paged back to the
pull cursor. When the feed runs out before reaching the cursor, the daily
form index fills the days in between. Only filings by a tracked company
(a ticker with prices, mapped to its CIK by SEC's ticker list) are read.

Per filing:
  - skipped when its items are all routine (a vote result, a bylaw change,
    an unregistered share sale, exhibits only) or a financing (1.01 with
    2.03): mart.news_digest.routine_items decides
  - the index page: the items, the acceptance time, the documents
  - the press release (EX-99.1, else EX-99 or EX-99.01), else the 8-K
    itself; 7.01 or 8.01 with no press release is routine and skipped
  - the headline is the release's title line, or "{company}: {item}" for
    an 8-K body; the summary is the opening paragraph

The cursor is the newest acceptance time read, held back to just before
the earliest filing that failed (a timeout, a 5xx, a document not yet
online), so the next run reads it again. Accessions already landed are
skipped, so a held-back cursor costs no repeat requests.
"""

from __future__ import annotations

import html as html_lib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..mart.news_digest import routine_items
from ..staging.article_text import extract_text
from ..storage import Warehouse
from .clients.base import APIError, InvalidResponseError, NotFoundError, RateLimitError
from .clients.sec_edgar import WWW
from .raw_mapping import article_id, primary_news_rows

NEW_YORK = ZoneInfo("America/New_York")
ATOM = "{http://www.w3.org/2005/Atom}"

FORMS = frozenset({"8-K"})  # an 8-K/A repeats or corrects news already out
FEED_PAGE = 100
MAX_FEED_PAGES = 40         # 4,000 filings, about two busy days
FIRST_LOOKBACK = timedelta(hours=36)
MAX_FILINGS = 300           # tracked filings read per run, a cap for backfills
RETRY_WINDOW = timedelta(days=2)  # a failed filing holds the cursor back this long at most
KNOWN_DAYS = 14             # landed accessions read back this far, to skip repeats
MIN_INTERVAL = 0.2          # seconds between SEC requests: 5 a second
SOURCE = "SEC filing"
FEED = "sec_8k"

# control.watermarks key of the pull cursor
CURSOR_ENDPOINT = "sec_8k_releases"
CURSOR_DIMENSION = "cursor"

# Short names for the headline of a filing with no press release.
ITEM_NAMES: dict[str, str] = {
    "1.01": "material agreement", "1.02": "material agreement terminated",
    "1.03": "bankruptcy or receivership", "1.04": "mine safety",
    "1.05": "cybersecurity incident", "2.01": "acquisition or disposal completed",
    "2.02": "results of operations", "2.03": "new financial obligation",
    "2.04": "obligation accelerated", "2.05": "exit or disposal costs",
    "2.06": "material impairment", "3.01": "listing notice or transfer",
    "3.02": "unregistered share sale", "3.03": "change to shareholder rights",
    "4.01": "auditor change", "4.02": "past financial statements no longer reliable",
    "5.01": "change in control", "5.02": "director or officer change",
    "5.03": "bylaw or fiscal year change", "5.04": "benefit plan trading suspension",
    "5.05": "code of ethics change", "5.06": "shell company status change",
    "5.07": "shareholder vote results", "5.08": "director nominations",
    "6.01": "asset-backed securities", "7.01": "Regulation FD disclosure",
    "8.01": "other events", "9.01": "exhibits",
}

_RELEASE_TYPES = ("EX-99.1", "EX-99", "EX-99.01")
_TITLE_CIK = re.compile(r"\((\d{10})\)")
_TITLE_NAME = re.compile(r"^\S+ - (.+?) \(\d{10}\)")
_ITEM = re.compile(r"Item\s+(\d\.\d\d)")
_ACCESSION = re.compile(r"accession-number=(\d{10}-\d{2}-\d{6})")
_INDEX_ROW = re.compile(
    r"^(?P<form>\S+(?: \S+)*?)\s{2,}(?P<company>.+?)\s{2,}(?P<cik>\d+)\s{2,}(?P<filed>\d{8})\s{2,}"
    r"(?P<path>edgar/data/\S+?/(?P<accession>\d{10}-\d{2}-\d{6})\.txt)\s*$")


@dataclass(frozen=True)
class Filing:
    """One 8-K as discovery saw it; items and acceptance time may be
    unknown until its index page is read (a filing from the daily index)."""

    accession: str
    cik: str              # without leading zeros
    company: str          # EDGAR's name for the filer
    form: str
    index_url: str
    accepted: datetime | None = None  # UTC
    items: tuple[str, ...] = ()
    filed: date | None = None


@dataclass(frozen=True)
class Company:
    tickers: tuple[str, ...]
    name: str
    market_cap: float | None = None


@dataclass(frozen=True)
class PullPlan:
    since: datetime                   # the cursor, UTC
    companies: dict[str, Company]     # by CIK
    known: frozenset[str]             # accession numbers already landed


@dataclass
class Pulled:
    """What a fetch produced, for landing and the run log."""

    articles: list[dict[str, Any]] = field(default_factory=list)
    cursor: datetime | None = None
    requests: int = 0
    filings: int = 0                  # tracked filings found
    skipped: Counter = field(default_factory=Counter)
    failed: list[str] = field(default_factory=list)
    gap_days: list[str] = field(default_factory=list)
    capped: bool = False
    rate_limited: bool = False


# --- parsing ----------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC)


def parse_feed(xml: str) -> list[Filing]:
    """The entries of one latest-filings Atom page."""
    root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    filings = []
    for e in root.findall(f"{ATOM}entry"):
        title = e.findtext(f"{ATOM}title") or ""
        cik = _TITLE_CIK.search(title)
        link = e.find(f"{ATOM}link")
        category = e.find(f"{ATOM}category")
        accession = _ACCESSION.search(e.findtext(f"{ATOM}id") or "")
        updated = e.findtext(f"{ATOM}updated")
        if not (cik and link is not None and accession and updated):
            continue
        name = _TITLE_NAME.search(title)
        filings.append(Filing(
            accession=accession.group(1),
            cik=str(int(cik.group(1))),
            company=name.group(1).strip() if name else "",
            form=category.get("term", "") if category is not None else "",
            index_url=link.get("href", ""),
            accepted=_utc(datetime.fromisoformat(updated)),
            items=tuple(dict.fromkeys(_ITEM.findall(e.findtext(f"{ATOM}summary") or ""))),
        ))
    return filings


def parse_form_index(text: str) -> list[Filing]:
    """The rows of a daily form index (form.YYYYMMDD.idx)."""
    filings = []
    for line in text.splitlines():
        m = _INDEX_ROW.match(line)
        if not m:
            continue
        cik = str(int(m["cik"]))
        acc = m["accession"]
        filings.append(Filing(
            accession=acc, cik=cik, company=m["company"].strip(), form=m["form"],
            index_url=f"{WWW}/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm",
            filed=date(int(m["filed"][:4]), int(m["filed"][4:6]), int(m["filed"][6:])),
        ))
    return filings


@dataclass(frozen=True)
class FilingIndex:
    items: tuple[str, ...]
    accepted: datetime | None                 # UTC
    documents: tuple[tuple[str, str], ...]    # (type, absolute URL), in filing order


def _cell_text(cell: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", cell)).split())


def parse_index(page: str) -> FilingIndex:
    """A filing index page: its items, acceptance time (New York time on
    the page) and the documents of its first table."""
    def info(head: str) -> str | None:
        m = re.search(rf'<div class="infoHead">{head}</div>\s*<div class="info">(.*?)</div>', page, re.DOTALL)
        return m.group(1) if m else None

    items = tuple(dict.fromkeys(_ITEM.findall(_cell_text(info("Items") or ""))))
    accepted = None
    if raw := info("Accepted"):
        try:
            accepted = _utc(datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=NEW_YORK))
        except ValueError:
            accepted = None
    documents = []
    table = re.search(r'<table class="tableFile"[^>]*>(.*?)</table>', page, re.DOTALL)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1) if table else "", re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        href = re.search(r'href="([^"]+)"', row)
        if len(cells) < 4 or not href:
            continue
        path = html_lib.unescape(href.group(1)).replace("/ix?doc=", "")
        documents.append((_cell_text(cells[3]).upper(), path if path.startswith("http") else f"{WWW}{path}"))
    return FilingIndex(items, accepted, tuple(documents))


def pick_document(documents: Iterable[tuple[str, str]], form: str = "8-K") -> tuple[str, str] | None:
    """The press release if the filing has one, else the form itself."""
    docs = list(documents)
    for kind in _RELEASE_TYPES:
        for doc in docs:
            if doc[0] == kind:
                return doc
    return next((d for d in docs if d[0] == form), None)


_BOILERPLATE = re.compile(
    r"^(?:exhibit\s*99(?:\.\d+)?|(?:news|press|earnings)\s+release|for immediate release|news"
    r"|(?:media|investor|press)?\s*contacts?|investor relations|page \d+)\b[\s:.\-–]*", re.IGNORECASE)
_SMALL = frozenset([
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to",
    "vs", "with"
])


def _title_case(line: str) -> str:
    """An all-caps title line in title case, so it reads like the others."""
    if not line.isupper():
        return line
    words = line.lower().split()
    return " ".join(
        w if any(c.isdigit() for c in w) else (w if i and w in _SMALL else w[:1].upper() + w[1:])
        for i, w in enumerate(words))


def release_title(lines: list[str]) -> str | None:
    """The press release's title: its first line of 4 to 30 words that
    isn't an exhibit label, a 'press release' banner or a contact line."""
    for line in lines[:8]:
        if _BOILERPLATE.fullmatch(line.strip()):
            continue
        words = line.split()
        if len(words) < 4:
            continue
        return _title_case(line.strip()) if len(words) <= 30 else None
    return None


def opening(lines: list[str], skip: str | None = None, limit: int = 600) -> str | None:
    """The first paragraph of 20 words or more, cut to about `limit`
    characters at a sentence end."""
    for line in lines:
        if line == skip or len(line.split()) < 20:
            continue
        if len(line) <= limit:
            return line
        cut = line[:limit]
        end = max(cut.rfind(". "), cut.rfind("; "))
        return cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "…"
    return None


def headline_and_summary(text: str, released: bool, company: str,
                         items: Iterable[str]) -> tuple[str, str | None]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = release_title(lines) if released else None
    if title is None:
        first = next((i for i in items if i != "9.01"), None)
        title = f"{company}: {ITEM_NAMES.get(first, 'current report')}" if first else f"{company}: current report"
    return title, opening(lines, skip=title)


# --- plan -------------------------------------------------------------------

def plan(warehouse: Warehouse, now: datetime) -> PullPlan:
    """The cursor, the tracked companies by CIK and the accessions already
    landed."""
    with warehouse.connect(read_only=True) as con:
        row = con.execute(
            "SELECT high_watermark FROM control.watermarks WHERE endpoint = ? AND dimension_key = ?",
            [CURSOR_ENDPOINT, CURSOR_DIMENSION],
        ).fetchone()
        rows = con.execute(
            """
            WITH tracked AS (SELECT DISTINCT ticker FROM staging.stg_prices_daily)
            SELECT json_extract_string(s.payload, '$.cik_str') AS cik,
                   list(t.ticker ORDER BY t.ticker) AS tickers,
                   COALESCE(any_value(json_extract_string(p.payload, '$.name')),
                            any_value(json_extract_string(s.payload, '$.title'))) AS name,
                   max(TRY_CAST(json_extract_string(p.payload, '$.marketCapitalization') AS DOUBLE))
            FROM tracked t
            JOIN raw.raw_sec_company_tickers s
              ON regexp_replace(s.ticker, '[./]', '-', 'g') = regexp_replace(t.ticker, '[./]', '-', 'g')
            LEFT JOIN raw.raw_company_profile p ON p.ticker = t.ticker
            GROUP BY 1
            """
        ).fetchall()
        known = con.execute(
            """
            SELECT json_extract_string(payload, '$.accession_number') FROM raw.raw_news_articles
            WHERE json_extract_string(payload, '$.feed') = ? AND fetched_at >= ?
            """,
            [FEED, now - timedelta(days=KNOWN_DAYS)],
        ).fetchall()
    since = (_utc(datetime.fromisoformat(row[0])) if row and row[0] else now - FIRST_LOOKBACK)
    companies = {str(int(cik)): Company(tuple(tk), name or "", cap)
                 for cik, tk, name, cap in rows if cik}
    return PullPlan(since=since, companies=companies, known=frozenset(a for (a,) in known if a))


# --- fetch ------------------------------------------------------------------

def _weekdays(first: date, last: date) -> list[date]:
    days = []
    d = first
    while d <= last:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def discover(client: Any, p: PullPlan, now: datetime, out: Pulled) -> list[Filing]:
    """Tracked, not yet landed 8-Ks accepted after the cursor, oldest first."""
    found: dict[str, Filing] = {}
    newest: datetime | None = None
    oldest: datetime | None = None
    reached = False
    for page in range(MAX_FEED_PAGES):
        entries = parse_feed(client.current_filings("8-K", start=page * FEED_PAGE, count=FEED_PAGE))
        out.requests += 1
        for f in entries:
            accepted = f.accepted
            if accepted is None:  # parse_feed keeps only entries with a time
                continue
            newest = max(newest or accepted, accepted)
            oldest = min(oldest or accepted, accepted)
            if accepted <= p.since:
                reached = True
            elif f.form in FORMS and f.cik in p.companies and f.accession not in p.known:
                found.setdefault(f.accession, f)
        if reached or len(entries) < FEED_PAGE:
            break

    if not reached:
        # the feed ends after the cursor: the daily index covers the days between
        last = (oldest or now).astimezone(NEW_YORK).date()
        for day in _weekdays(p.since.astimezone(NEW_YORK).date(), last):
            try:
                text = client.daily_form_index(day)
            except NotFoundError:  # no index for a holiday, or not yet for today
                continue
            finally:
                out.requests += 1
            out.gap_days.append(day.isoformat())
            for f in parse_form_index(text):
                if f.form in FORMS and f.cik in p.companies and f.accession not in p.known:
                    found.setdefault(f.accession, f)

    out.cursor = newest
    return sorted(found.values(), key=lambda f: (_when(f, now), f.accession))


def read_filing(client: Any, f: Filing, company: Company, since: datetime,
                out: Pulled) -> dict[str, Any] | None:
    """The filing's article payload, or None when it is routine or older
    than the cursor. Network errors propagate to the caller."""
    if f.items and routine_items(f.items):
        out.skipped["routine"] += 1
        return None
    index = parse_index(client.page(f.index_url))
    out.requests += 1
    items = f.items or index.items
    accepted = f.accepted or index.accepted
    if accepted is None or accepted <= since:
        out.skipped["before_cursor"] += 1
        return None
    if routine_items(items):
        out.skipped["routine"] += 1
        return None
    doc = pick_document(index.documents, f.form)
    if doc is None:
        out.skipped["no_document"] += 1
        return None
    released = doc[0] != f.form
    if not released and routine_items(items, released=False):
        out.skipped["no_release"] += 1
        return None
    page = client.page(doc[1])
    out.requests += 1
    text = extract_text(page, doc[1])
    headline, summary = headline_and_summary(text.text, released, company.name or f.company, items)
    return {
        "article_id": article_id(doc[1]),
        "provider": "sec_edgar",
        "feed": FEED,
        "title": headline,
        "time_published": accepted.strftime("%Y%m%dT%H%M%S"),
        "ticker_sentiment": [{"ticker": t} for t in company.tickers],
        "source": SOURCE,
        "summary": summary,
        "url": doc[1],
        "cik": f.cik,
        "accession_number": f.accession,
        "form": f.form,
        "items": list(items),
        "company": company.name or f.company,
        "document_type": doc[0],
        "index_url": f.index_url,
        "words": text.words,
    }


def fetch(client: Any, p: PullPlan, now: datetime, max_filings: int = MAX_FILINGS) -> Pulled:
    """Discover and read the filings; network only."""
    out = Pulled()
    try:
        filings = discover(client, p, now, out)
    except RateLimitError:
        out.rate_limited = True
        out.cursor = None
        return out
    out.filings = len(filings)
    hold: datetime | None = None  # the cursor may not pass this
    for i, f in enumerate(filings):
        if i == max_filings:
            out.capped = True
            hold = _before(f, now)
            break
        try:
            article = read_filing(client, f, p.companies[f.cik], p.since, out)
        except RateLimitError:
            out.rate_limited = True
            hold = _before(f, now)
            break
        except (APIError, InvalidResponseError, httpx.HTTPError, ET.ParseError) as exc:
            out.failed.append(f"{f.accession}: {type(exc).__name__}")
            if f.accepted is None or now - f.accepted < RETRY_WINDOW:
                at = _before(f, now)
                hold = at if hold is None else min(hold, at)
            continue
        if article is not None:
            out.articles.append(article)
    if hold is not None:
        out.cursor = min(out.cursor, hold) if out.cursor else hold
    if out.cursor is not None:
        out.cursor = max(out.cursor, p.since)  # never back past where this run began
    return out


def _when(f: Filing, now: datetime) -> datetime:
    """When the filing was accepted, or the start of the day it was filed
    (New York time) for one from the daily index."""
    return f.accepted or _utc(datetime.combine(f.filed or now.date(), datetime.min.time(), NEW_YORK))


def _before(f: Filing, now: datetime) -> datetime:
    """Just before the filing, so the next pull reads it again."""
    return _when(f, now) - timedelta(microseconds=1)


# --- land -------------------------------------------------------------------

def land(warehouse: Warehouse, pulled: Pulled, now: datetime) -> int:
    rows = primary_news_rows(pulled.articles)
    written = 0
    for artifact, artifact_rows in rows.items():
        if artifact_rows:
            written += warehouse.land(artifact, artifact_rows, fetched_at=now)
    if pulled.cursor is not None:
        warehouse.upsert_watermark(CURSOR_ENDPOINT, CURSOR_DIMENSION, fetched_at=now,
                                   high_watermark=pulled.cursor.isoformat())
    return written


def pull_8k_releases(warehouse: Warehouse, client: Any, *, now: datetime | None = None,
                     max_filings: int = MAX_FILINGS) -> dict:
    """Plan, fetch and land the tracked companies' new 8-Ks; returns what
    happened, for the run log."""
    now = now or datetime.now(UTC)
    p = plan(warehouse, now)
    if not p.companies:
        return {"companies": 0, "filings": 0, "landed": 0, "requests": 0,
                "note": "no tracked company has a CIK yet (sec_company_tickers not landed?)"}
    pulled = fetch(client, p, now, max_filings)
    land(warehouse, pulled, now)
    return {
        "companies": len(p.companies),
        "since": p.since.isoformat(),
        "cursor": pulled.cursor.isoformat() if pulled.cursor else None,
        "filings": pulled.filings,
        "landed": len(pulled.articles),
        "skipped": dict(pulled.skipped),
        "failed": pulled.failed,
        "gap_days": pulled.gap_days,
        "requests": pulled.requests,
        "capped": pulled.capped,
        "rate_limited": pulled.rate_limited,
    }


def new_client() -> Any:
    from .clients.sec_edgar import SecEdgarClient

    return SecEdgarClient(min_interval_seconds=MIN_INTERVAL)


__all__ = [
    "Company", "Filing", "FilingIndex", "PullPlan", "Pulled", "discover", "fetch",
    "headline_and_summary", "land", "new_client", "opening", "parse_feed", "parse_form_index",
    "parse_index", "pick_document", "plan", "pull_8k_releases", "read_filing", "release_title",
]
