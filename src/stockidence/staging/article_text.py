"""Staging: raw.news_article_pages HTML -> staging.stg_news_article_text.

Registry: news_article.text (derived, watermark url). The main text of each
fetched page, without menus, ads and related-story links, cut to the first
MAX_WORDS words: enough for the story's facts, and it keeps long pages such
as full earnings-call transcripts from crowding the model's context.

Forms and pop-up dialogs (sign-in walls, newsletter boxes) are removed
before extraction: they are never article text, and the extractor can
otherwise take a sign-in form for the start of the article. Sections next
to the article, such as a company profile, can still come through.

SEC filings get two more steps. A document read from a filing's archive can
come inside EDGAR's SGML envelope (<DOCUMENT><TYPE>EX-99.1 … <TEXT>), which
the HTML parser takes for the page, so the HTML inside it is read instead.
An 8-K's own text loses its cover page (registrant details and check boxes)
and its signature block, leaving the items it reports.

Incremental: only pages with no text yet, or text from an older extractor
version, are extracted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import trafilatura
from trafilatura.utils import load_html

from ..storage import Warehouse

MAX_WORDS = 1500
# Stored with each row; a page is re-extracted when this changes, so change
# it with the library version or with the cleaning below.
EXTRACTOR = f"trafilatura {trafilatura.__version__}, forms dropped, filing covers dropped"
NOT_ARTICLE = "//form | //dialog | //*[@role='dialog' or @aria-modal='true']"

_ENVELOPE = re.compile(r"<(?:DOCUMENT|TYPE|SEQUENCE|FILENAME)>", re.IGNORECASE)
_HTML_START = re.compile(r"<html[\s>]", re.IGNORECASE)
_FORM_8K = re.compile(r"form\s+8-k(?:/a)?", re.IGNORECASE)
_COVER_END = re.compile(r"emerging growth company", re.IGNORECASE)
_ITEM = re.compile(r"item\s+\d\.\d{2}\b", re.IGNORECASE)
_SIGNATURES = re.compile(r"signatures?", re.IGNORECASE)


@dataclass(frozen=True)
class ArticleText:
    text: str
    words: int  # in the whole article, before the cut
    truncated: bool


def cap_words(text: str, limit: int = MAX_WORDS) -> ArticleText:
    """The first `limit` words of `text`, keeping its paragraph breaks."""
    kept: list[str] = []
    n = 0
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            continue
        if n + len(words) > limit:
            if n < limit:
                kept.append(" ".join(words[: limit - n]))
            break
        kept.append(" ".join(words))
        n += len(words)
    total = len(text.split())
    return ArticleText("\n".join(kept), total, total > limit)


def unwrap_filing(html: str) -> str:
    """The HTML inside an EDGAR document's SGML envelope; other pages as they are."""
    start = _HTML_START.search(html)
    if start is None or not _ENVELOPE.search(html, 0, start.start()):
        return html
    end = html.lower().rfind("</html>")
    return html[start.start() : end + len("</html>") if end > start.start() else len(html)]


def drop_filing_cover(text: str) -> str:
    """An 8-K's items without its cover page and signature block; any other
    text as it is.

    The cover ends with the emerging-growth-company check boxes. When those
    aren't found, the report starts at its first 'Item X.XX' heading.
    """
    lines = text.splitlines()
    if not any(_FORM_8K.fullmatch(line.strip()) for line in lines[:12]):
        return text
    start = None
    for i, line in enumerate(lines[:60]):
        if _COVER_END.search(line):
            start = i + 1
    if start is None:
        start = next((i for i, line in enumerate(lines) if _ITEM.match(line.strip())), None)
        if start is None:
            return text
    end = next(
        (i for i in range(start, len(lines)) if _SIGNATURES.fullmatch(lines[i].strip())), len(lines)
    )
    return "\n".join(lines[start:end])


def extract_text(html: str, url: str | None = None) -> ArticleText:
    """The article's main text; empty when the page has none to find."""
    tree = load_html(unwrap_filing(html))
    if tree is None:
        return ArticleText("", 0, False)
    for el in tree.xpath(NOT_ARTICLE):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    text = trafilatura.extract(tree, url=url, include_comments=False, include_tables=False) or ""
    return cap_words(drop_filing_cover(text))


def rebuild_article_text(warehouse: Warehouse, now: datetime | None = None) -> int:
    """Extract every page not yet extracted by this extractor version.

    Reads, closes the connection, extracts, then writes, so the warehouse is
    never held while pages are parsed.
    """
    now = now or datetime.now(UTC)
    with warehouse.connect(read_only=True) as con:
        pages = con.execute(
            """
            SELECT p.url, p.html
            FROM raw.news_article_pages p
            LEFT JOIN staging.stg_news_article_text t USING (url)
            WHERE p.html IS NOT NULL AND (t.url IS NULL OR t.extractor <> ?)
            """,
            [EXTRACTOR],
        ).fetchall()
    if not pages:
        return 0
    rows = []
    for url, html in pages:
        a = extract_text(html, url)
        rows.append([url, a.text, a.words, a.truncated, EXTRACTOR, now])
    with warehouse.connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO staging.stg_news_article_text"
            " (url, text, words, truncated, extractor, extracted_at) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)
