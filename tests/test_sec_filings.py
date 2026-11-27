"""Company stories from 8-K filings: parsing EDGAR's feed, daily index and
filing pages, reading a filing, the pull cursor, and the pull end to end on
a temporary warehouse. A fake client stands in for EDGAR: no network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from stockidence.ingest.clients.base import APIError, NotFoundError, RateLimitError
from stockidence.ingest.endpoints import Provider
from stockidence.ingest.engine import IngestEngine
from stockidence.ingest.sec_filings import (
    CURSOR_DIMENSION,
    CURSOR_ENDPOINT,
    Company,
    Filing,
    PullPlan,
    fetch,
    headline_and_summary,
    opening,
    parse_feed,
    parse_form_index,
    parse_index,
    pick_document,
    pull_8k_releases,
    read_filing,
    release_title,
)
from stockidence.staging.staging import rebuild_news_articles
from stockidence.storage import Warehouse

WWW = "https://www.sec.gov"


# --- fixtures: EDGAR's pages, cut down to what is read -----------------------


def _index_url(cik, acc):
    return f"{WWW}/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index.htm"


def _doc_url(cik, acc, name):
    return f"{WWW}/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{name}"


def _entry(acc, cik, name, items, updated, form="8-K"):
    lines = "".join(f"\n&lt;br&gt;Item {i}: Something" for i in items)
    return f"""<entry>
<title>{form} - {name} ({cik:010d}) (Filer)</title>
<link rel="alternate" type="text/html" href="{_index_url(cik, acc)}"/>
<summary type="html">
 &lt;b&gt;Filed:&lt;/b&gt; 2026-11-25 &lt;b&gt;AccNo:&lt;/b&gt; {acc} &lt;b&gt;Size:&lt;/b&gt; 154 KB{lines}
</summary>
<updated>{updated}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{form}"/>
<id>urn:tag:sec.gov,2008:accession-number={acc}</id>
</entry>"""


def _feed(*entries):
    return (
        '<?xml version="1.0" encoding="ISO-8859-1" ?>\n<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "<title>Latest Filings</title>\n" + "".join(entries) + "\n</feed>"
    )


def _index(accepted, items, docs):
    """A filing index page: docs are (description, path, type)."""
    rows = "".join(
        f'<tr><td scope="row">{n}</td><td scope="row">{desc}</td>'
        f'<td scope="row"><a href="{path}">{path.rsplit("/", 1)[-1]}</a></td>'
        f'<td scope="row">{typ}</td><td scope="row">100</td></tr>\n'
        for n, (desc, path, typ) in enumerate(docs, start=1)
    )
    item_lines = "".join(f"Item {i}: Something<br />" for i in items)
    return f"""<div class="formGrouping">
<div class="infoHead">Filing Date</div>
<div class="info">2026-11-25</div>
<div class="infoHead">Accepted</div>
<div class="info">{accepted}</div>
</div>
<div class="formGrouping">
<div class="infoHead">Items</div>
<div class="info">{item_lines}</div>
</div>
<table class="tableFile" summary="Document Format Files">
<tr><th scope="col">Seq</th><th scope="col">Description</th><th scope="col">Document</th>
<th scope="col">Type</th><th scope="col">Size</th></tr>
{rows}<tr class="evenRow"><td scope="row">&nbsp;</td><td scope="row">Complete submission text file</td>
<td scope="row"><a href="/Archives/edgar/data/1/x.txt">x.txt</a></td><td scope="row">&nbsp;</td><td>1</td></tr>
</table>
<table class="tableFile" summary="Data Files">
<tr><td scope="row">9</td><td scope="row">XBRL SCHEMA</td><td scope="row"><a href="/Archives/x.xsd">x.xsd</a></td>
<td scope="row">EX-101.SCH</td><td>1</td></tr>
</table>"""


RELEASE = """<html><head><title>ex99-1</title></head><body>
<p>Exhibit 99.1</p>
<p>NEWS RELEASE</p>
<p><b>ACME CORP REPORTS THIRD QUARTER 2026 RESULTS</b></p>
<p>SPRINGFIELD, Ill., Nov. 25, 2026 -- Acme Corp (NYSE: ACME) today reported third-quarter revenue of
$1.2 billion, up 8% from a year earlier, and raised its outlook for the full year on strong demand for its
industrial pumps.</p>
<p>"We delivered another quarter of steady growth," said Jane Doe, chief executive officer. "Our order
book has never been stronger, and we are investing to meet that demand across every region we serve."</p>
<p>Net income was $140 million, or $1.10 a share, compared with $120 million, or $0.95 a share, in the
third quarter of 2025. Operating margin widened by 1.5 percentage points to 18.2%.</p>
</body></html>"""

FILING = """<html><body>
<p>UNITED STATES</p><p>SECURITIES AND EXCHANGE COMMISSION</p><p>Washington, D.C. 20549</p>
<p>FORM 8-K</p>
<p>CURRENT REPORT</p>
<p>Pursuant to Section 13 or 15(d) of the Securities Exchange Act of 1934</p>
<p>Date of Report (Date of earliest event reported): November 24, 2026</p>
<p>WIDGET &amp; SONS INC</p>
<p>(Exact name of registrant as specified in its charter)</p>
<p>Indicate by check mark whether the registrant is an emerging growth company as defined in Rule 405 of
the Securities Act of 1933.</p>
<p>Emerging growth company</p>
<p>Item 5.02 Departure of Directors or Certain Officers; Election of Directors.</p>
<p>On November 24, 2026, John Roe informed the Board of Directors of Widget &amp; Sons Inc that he will not
stand for re-election as a director at the company's 2027 annual meeting of shareholders. His decision was
not the result of any disagreement with the company.</p>
<p>SIGNATURES</p>
<p>Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this
report to be signed on its behalf by the undersigned hereunto duly authorized.</p>
<p>WIDGET &amp; SONS INC</p><p>By: /s/ Jane Doe</p>
</body></html>"""

ACME, WIDGET = 1111, 2222
# accepted 17:30, 09:00, 10:00, 08:00 and 20:00 the evening before, New York time
A_RESULTS = "0001111111-26-000003"  # 2.02 with a press release: a story
A_AMEND = "0001111111-26-000004"  # an 8-K/A: not read
OTHER = "0009999999-26-000001"  # an untracked filer: not read
W_VOTE = "0002222222-26-000001"  # vote results: routine on the feed's items alone
W_DIRECTOR = "0002222222-26-000002"  # 5.02 with no press release: a story from the 8-K
A_OTHER = "0001111111-26-000002"  # 8.01 with no press release: routine once the index is read
A_OLD = "0001111111-26-000001"  # before the cursor

ENTRIES = (
    _entry(A_AMEND, ACME, "Acme Corp", ["2.02"], "2026-11-25T17:40:00-05:00", form="8-K/A"),
    _entry(A_RESULTS, ACME, "Acme Corp", ["2.02", "9.01"], "2026-11-25T17:30:00-05:00"),
    _entry(OTHER, 9999999, "Someone Else Inc", ["8.01"], "2026-11-25T16:00:00-05:00"),
    _entry(W_VOTE, WIDGET, "Widget &amp; Sons Inc", ["5.07", "9.01"], "2026-11-25T10:00:00-05:00"),
    _entry(W_DIRECTOR, WIDGET, "Widget &amp; Sons Inc", ["5.02"], "2026-11-25T09:00:00-05:00"),
    _entry(A_OTHER, ACME, "Acme Corp", ["8.01", "9.01"], "2026-11-25T08:00:00-05:00"),
    _entry(A_OLD, ACME, "Acme Corp", ["2.02", "9.01"], "2026-11-24T20:00:00-05:00"),
)

PAGES = {
    _index_url(ACME, A_RESULTS): _index(
        "2026-11-25 17:30:00",
        ["2.02", "9.01"],
        [
            ("8-K", f"/ix?doc=/Archives/edgar/data/{ACME}/000111111126000003/acme-8k.htm", "8-K"),
            ("EX-99.1", f"/Archives/edgar/data/{ACME}/000111111126000003/ex99-1.htm", "EX-99.1"),
            ("", f"/Archives/edgar/data/{ACME}/000111111126000003/logo.jpg", "GRAPHIC"),
        ],
    ),
    _doc_url(ACME, A_RESULTS, "ex99-1.htm"): RELEASE,
    _index_url(WIDGET, W_DIRECTOR): _index(
        "2026-11-25 09:00:00",
        ["5.02"],
        [
            ("8-K", f"/Archives/edgar/data/{WIDGET}/000222222226000002/widget-8k.htm", "8-K"),
        ],
    ),
    _doc_url(WIDGET, W_DIRECTOR, "widget-8k.htm"): FILING,
    _index_url(ACME, A_OTHER): _index(
        "2026-11-25 08:00:00",
        ["8.01", "9.01"],
        [
            ("8-K", f"/Archives/edgar/data/{ACME}/000111111126000002/acme-8k.htm", "8-K"),
            ("EX-10.1", f"/Archives/edgar/data/{ACME}/000111111126000002/ex10-1.htm", "EX-10.1"),
        ],
    ),
}


class FakeSec:
    """EDGAR's archive from canned pages; a value that is an exception is
    raised instead. Records each request."""

    def __init__(self, feed_pages=(), pages=None, indexes=None):
        self.feed_pages = list(feed_pages)
        self.pages = dict(PAGES if pages is None else pages)
        self.indexes = dict(indexes or {})
        self.calls: list[tuple] = []

    def current_filings(self, form="8-K", start=0, count=100):
        self.calls.append(("feed", start))
        page = start // count
        return self.feed_pages[page] if page < len(self.feed_pages) else _feed()

    def daily_form_index(self, day):
        self.calls.append(("daily_index", day))
        value = self.indexes.get(day, NotFoundError("HTTP 404"))
        if isinstance(value, Exception):
            raise value
        return value

    def page(self, url):
        self.calls.append(("page", url))
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


NOW = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
SINCE = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)  # 07:00 New York time
COMPANIES = {"1111": Company(("ACME",), "Acme Corp", 50_000.0), "2222": Company(("WIDG",), "")}


def _plan(since=SINCE, known=()):
    return PullPlan(since=since, companies=COMPANIES, known=frozenset(known))


def _ny(text):
    return datetime.fromisoformat(text).astimezone(UTC)


# --- parsing ---------------------------------------------------------------


def test_parse_feed():
    filings = {f.accession: f for f in parse_feed(_feed(*ENTRIES))}
    assert len(filings) == 7
    f = filings[A_RESULTS]
    assert f == Filing(
        accession=A_RESULTS,
        cik="1111",
        company="Acme Corp",
        form="8-K",
        index_url=_index_url(ACME, A_RESULTS),
        accepted=datetime(2026, 11, 25, 22, 30, tzinfo=UTC),
        items=("2.02", "9.01"),
    )
    assert filings[W_VOTE].company == "Widget & Sons Inc"
    assert filings[A_AMEND].form == "8-K/A"


def test_parse_feed_skips_entries_it_cannot_place():
    broken = _entry(A_RESULTS, ACME, "Acme Corp", ["2.02"], "2026-11-25T17:30:00-05:00").replace(
        "accession-number=", "something-else="
    )
    assert parse_feed(_feed(broken)) == []


def test_parse_form_index():
    text = """Description:           Daily Index of EDGAR Dissemination Feed by Form Type
Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------
8-K         ACME CORP                                                     1111        20261124    edgar/data/1111/0001111111-26-000001.txt
8-K/A       ACME CORP                                                     1111        20261124    edgar/data/1111/0001111111-26-000009.txt
10-Q        WIDGET & SONS INC                                             2222        20261124    edgar/data/2222/0002222222-26-000009.txt
"""
    filings = parse_form_index(text)
    assert [(f.form, f.cik, f.accession) for f in filings] == [
        ("8-K", "1111", "0001111111-26-000001"),
        ("8-K/A", "1111", "0001111111-26-000009"),
        ("10-Q", "2222", "0002222222-26-000009"),
    ]
    assert filings[0].company == "ACME CORP" and filings[0].filed == date(2026, 11, 24)
    assert filings[0].index_url == _index_url(ACME, "0001111111-26-000001")
    assert filings[0].accepted is None and filings[0].items == ()


def test_parse_index():
    index = parse_index(PAGES[_index_url(ACME, A_RESULTS)])
    assert index.items == ("2.02", "9.01")
    assert index.accepted == datetime(2026, 11, 25, 22, 30, tzinfo=UTC)  # New York time on the page
    assert index.documents == (
        (
            "8-K",
            f"{WWW}/Archives/edgar/data/{ACME}/000111111126000003/acme-8k.htm",
        ),  # the iXBRL viewer unwrapped
        ("EX-99.1", f"{WWW}/Archives/edgar/data/{ACME}/000111111126000003/ex99-1.htm"),
        ("GRAPHIC", f"{WWW}/Archives/edgar/data/{ACME}/000111111126000003/logo.jpg"),
        ("", f"{WWW}/Archives/edgar/data/1/x.txt"),
    )  # the data files' table is not read


def test_parse_index_in_standard_time_and_without_a_time():
    assert parse_index(_index("2026-01-15 16:05:00", ["2.02"], [])).accepted == datetime(
        2026, 1, 15, 21, 5, tzinfo=UTC
    )
    assert parse_index(_index("not a time", ["2.02"], [])).accepted is None


@pytest.mark.parametrize(
    "documents, picked",
    [
        ([("8-K", "a"), ("EX-99.1", "b"), ("EX-99.2", "c")], ("EX-99.1", "b")),
        ([("8-K", "a"), ("EX-99", "b")], ("EX-99", "b")),
        ([("8-K", "a"), ("EX-99.01", "b")], ("EX-99.01", "b")),
        ([("8-K", "a"), ("EX-10.1", "b")], ("8-K", "a")),
        ([("EX-10.1", "b")], None),
    ],
)
def test_pick_document_prefers_the_press_release(documents, picked):
    assert pick_document(documents) == picked


def test_release_title_skips_banners_and_title_cases_capitals():
    lines = [
        "Exhibit 99.1",
        "NEWS RELEASE",
        "For Immediate Release",
        "ACME CORP REPORTS THIRD QUARTER 2026 RESULTS",
        "SPRINGFIELD -- Acme Corp today ...",
    ]
    assert release_title(lines) == "Acme Corp Reports Third Quarter 2026 Results"
    assert (
        release_title(["Acme Names Jane Doe Chief Executive"])
        == "Acme Names Jane Doe Chief Executive"
    )
    assert release_title(["Short", "Too short too"]) is None


def test_opening_is_the_first_real_paragraph_cut_at_a_sentence():
    long = "Acme Corp today reported results for the quarter. " * 20
    assert opening(["Acme", "Too short to be the opening paragraph of anything.", long]).endswith(
        "quarter."
    )
    assert len(opening([long], limit=200)) <= 200
    assert opening(["a few words"]) is None


def test_headline_and_summary():
    released = (
        "Exhibit 99.1\nNEWS RELEASE\nACME CORP REPORTS THIRD QUARTER 2026 RESULTS\n"
        "SPRINGFIELD, Ill., Nov. 25, 2026 -- Acme Corp today reported third-quarter revenue of $1.2 "
        "billion, up 8% from a year earlier, and raised its outlook for the year."
    )
    headline, summary = headline_and_summary(released, True, "Acme Corp", ["2.02", "9.01"])
    assert headline == "Acme Corp Reports Third Quarter 2026 Results"
    assert summary.startswith("SPRINGFIELD, Ill.")
    body = (
        "Item 5.02 Departure of Directors.\nOn November 24, 2026, John Roe informed the Board " * 3
    )
    headline, _ = headline_and_summary(body, False, "Widget & Sons Inc", ["9.01", "5.02"])
    assert headline == "Widget & Sons Inc: director or officer change"
    assert headline_and_summary("", False, "Acme Corp", ["9.99"])[0] == "Acme Corp: current report"


# --- reading a filing --------------------------------------------------------


def _filing(acc):
    return next(f for f in parse_feed(_feed(*ENTRIES)) if f.accession == acc)


def test_read_filing_with_a_press_release():
    from stockidence.ingest.sec_filings import Pulled

    client, out = FakeSec(), Pulled()
    article = read_filing(client, _filing(A_RESULTS), COMPANIES["1111"], SINCE, out)
    url = _doc_url(ACME, A_RESULTS, "ex99-1.htm")
    assert article["title"] == "Acme Corp Reports Third Quarter 2026 Results"
    assert article["summary"].startswith(
        "SPRINGFIELD, Ill., Nov. 25, 2026 -- Acme Corp (NYSE: ACME)"
    )
    assert {
        k: article[k]
        for k in (
            "provider",
            "feed",
            "source",
            "url",
            "time_published",
            "ticker_sentiment",
            "cik",
            "accession_number",
            "form",
            "items",
            "company",
            "document_type",
        )
    } == {
        "provider": "sec_edgar",
        "feed": "sec_8k",
        "source": "SEC filing",
        "url": url,
        "time_published": "20261125T223000",
        "ticker_sentiment": [{"ticker": "ACME"}],
        "cik": "1111",
        "accession_number": A_RESULTS,
        "form": "8-K",
        "items": ["2.02", "9.01"],
        "company": "Acme Corp",
        "document_type": "EX-99.1",
    }
    assert article["words"] > 50 and len(article["article_id"]) == 16
    assert out.requests == 2 and client.calls == [
        ("page", _index_url(ACME, A_RESULTS)),
        ("page", url),
    ]


def test_read_filing_without_a_press_release_reads_the_8k():
    from stockidence.ingest.sec_filings import Pulled

    out = Pulled()
    article = read_filing(FakeSec(), _filing(W_DIRECTOR), COMPANIES["2222"], SINCE, out)
    assert (
        article["title"] == "Widget & Sons Inc: director or officer change"
    )  # the filer's name from EDGAR
    assert article["summary"].startswith("On November 24, 2026, John Roe informed the Board")
    assert article["document_type"] == "8-K" and article["ticker_sentiment"] == [{"ticker": "WIDG"}]


def test_read_filing_skips_routine_filings():
    from stockidence.ingest.sec_filings import Pulled

    client, out = FakeSec(), Pulled()
    assert read_filing(client, _filing(W_VOTE), COMPANIES["2222"], SINCE, out) is None
    assert client.calls == []  # the feed's items were enough
    assert read_filing(client, _filing(A_OTHER), COMPANIES["1111"], SINCE, out) is None
    assert out.skipped == {"routine": 1, "no_release": 1} and out.requests == 1


def test_read_filing_from_the_daily_index_takes_items_and_time_from_its_page():
    from stockidence.ingest.sec_filings import Pulled

    f = Filing(
        accession=A_RESULTS,
        cik="1111",
        company="ACME CORP",
        form="8-K",
        index_url=_index_url(ACME, A_RESULTS),
        filed=date(2026, 11, 25),
    )
    article = read_filing(FakeSec(), f, COMPANIES["1111"], SINCE, Pulled())
    assert article["items"] == ["2.02", "9.01"] and article["time_published"] == "20261125T223000"
    out = Pulled()
    assert (
        read_filing(FakeSec(), f, COMPANIES["1111"], datetime(2026, 11, 26, tzinfo=UTC), out)
        is None
    )
    assert out.skipped == {"before_cursor": 1}


# --- fetch: discovery and the cursor ----------------------------------------


def test_fetch_reads_tracked_new_filings_oldest_first():
    client = FakeSec([_feed(*ENTRIES)])
    out = fetch(client, _plan(), NOW)
    assert [a["accession_number"] for a in out.articles] == [W_DIRECTOR, A_RESULTS]
    assert out.filings == 4  # tracked, 8-K, after the cursor: vote, director, other events, results
    assert dict(out.skipped) == {"no_release": 1, "routine": 1}
    assert out.requests == 6 and out.failed == [] and not out.capped
    assert out.cursor == _ny("2026-11-25T17:40:00-05:00")  # the newest filing on the feed
    assert out.gap_days == []


def test_fetch_skips_filings_already_landed():
    client = FakeSec([_feed(*ENTRIES)])
    out = fetch(client, _plan(known={A_RESULTS, W_DIRECTOR}), NOW)
    assert out.articles == [] and out.filings == 2


def test_a_failed_filing_holds_the_cursor_back_for_the_next_run():
    pages = {**PAGES, _doc_url(WIDGET, W_DIRECTOR, "widget-8k.htm"): APIError("HTTP 503")}
    out = fetch(FakeSec([_feed(*ENTRIES)], pages), _plan(), NOW)
    assert [a["accession_number"] for a in out.articles] == [A_RESULTS]
    assert out.failed == [f"{W_DIRECTOR}: APIError"]
    assert out.cursor == _ny("2026-11-25T09:00:00-05:00") - timedelta(microseconds=1)


def test_a_filing_failing_for_days_stops_holding_the_cursor():
    pages = {**PAGES, _doc_url(WIDGET, W_DIRECTOR, "widget-8k.htm"): APIError("HTTP 503")}
    out = fetch(FakeSec([_feed(*ENTRIES)], pages), _plan(), NOW + timedelta(days=3))
    assert out.failed and out.cursor == _ny("2026-11-25T17:40:00-05:00")


def test_the_cap_stops_the_run_before_the_next_filing():
    out = fetch(FakeSec([_feed(*ENTRIES)]), _plan(), NOW, max_filings=2)
    assert out.capped and [a["accession_number"] for a in out.articles] == [W_DIRECTOR]
    assert out.cursor == _ny("2026-11-25T10:00:00-05:00") - timedelta(
        microseconds=1
    )  # the vote, read next run


def test_rate_limited_mid_run_keeps_what_was_read():
    pages = {**PAGES, _index_url(WIDGET, W_DIRECTOR): RateLimitError("HTTP 429")}
    out = fetch(FakeSec([_feed(*ENTRIES)], pages), _plan(), NOW)
    assert out.rate_limited and out.articles == []
    assert out.cursor == _ny("2026-11-25T09:00:00-05:00") - timedelta(microseconds=1)


def test_rate_limited_on_the_feed_leaves_the_cursor():
    class Limited(FakeSec):
        def current_filings(self, *args, **kwargs):
            raise RateLimitError("HTTP 429")

    out = fetch(Limited(), _plan(), NOW)
    assert out.rate_limited and out.cursor is None and out.articles == []


def test_the_cursor_never_moves_back():
    out = fetch(FakeSec([_feed(ENTRIES[-1])]), _plan(), NOW)  # only a filing from before the cursor
    assert out.articles == [] and out.cursor == SINCE


def test_the_daily_index_fills_the_days_the_feed_no_longer_reaches():
    since = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)  # Monday 07:00 New York time
    day_24 = (
        "8-K         ACME CORP                                                     1111        20261124"
        "    edgar/data/1111/0001111111-26-000001.txt\n"
        "8-K         SOMEONE ELSE INC                                              9999999     20261124"
        "    edgar/data/9999999/0009999999-26-000009.txt\n"
    )
    day_25 = (
        f"8-K         ACME CORP                                                     1111        20261125"
        f"    edgar/data/1111/{A_RESULTS}.txt\n"
    )
    pages = {
        **PAGES,
        _index_url(ACME, A_OLD): _index(
            "2026-11-24 20:00:00",
            ["2.02", "9.01"],
            [("EX-99.1", f"/Archives/edgar/data/{ACME}/000111111126000001/ex99-1.htm", "EX-99.1")],
        ),
        _doc_url(ACME, A_OLD, "ex99-1.htm"): RELEASE,
    }
    client = FakeSec(
        [_feed(*ENTRIES[:-1])], pages, {date(2026, 11, 24): day_24, date(2026, 11, 25): day_25}
    )
    out = fetch(client, _plan(since), NOW)
    # Monday has no index yet (404), so only Tuesday and Wednesday count as filled
    assert [c for c in client.calls if c[0] == "daily_index"] == [
        ("daily_index", date(2026, 11, 23)),
        ("daily_index", date(2026, 11, 24)),
        ("daily_index", date(2026, 11, 25)),
    ]
    assert out.gap_days == ["2026-11-24", "2026-11-25"]
    assert [a["accession_number"] for a in out.articles] == [A_OLD, W_DIRECTOR, A_RESULTS]
    assert (
        sum(1 for c in client.calls if c == ("page", _index_url(ACME, A_RESULTS))) == 1
    )  # once, from the feed


# --- the pull on a warehouse ------------------------------------------------


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "sec.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        for ticker, cik, title in (
            ("ACME", ACME, "ACME CORP"),
            ("WIDG", WIDGET, "WIDGET & SONS INC"),
            ("BRK-B", 1067983, "BERKSHIRE HATHAWAY INC"),
            ("ZZZZ", 5555, "UNTRACKED CO"),
        ):
            con.execute(
                "INSERT INTO raw.raw_sec_company_tickers VALUES (?, ?, ?)",
                [ticker, json.dumps({"cik_str": cik, "ticker": ticker, "title": title}), NOW],
            )
        for ticker in ("ACME", "WIDG", "BRK.B"):  # tracked: the tickers with prices
            con.execute(
                "INSERT INTO staging.stg_prices_daily VALUES (?, '2026-11-24', 1, 1, 1, 1, 1, 0.0)",
                [ticker],
            )
        con.execute(
            "INSERT INTO raw.raw_company_profile VALUES ('ACME', ?, ?)",
            [json.dumps({"name": "Acme Corp", "marketCapitalization": 50_000}), NOW],
        )
    return wh


def test_pull_lands_new_8ks_and_moves_the_cursor(warehouse):
    from stockidence.ingest.sec_filings import plan

    p = plan(warehouse, NOW)
    assert p.companies == {
        "1111": Company(("ACME",), "Acme Corp", 50_000.0),
        "2222": Company(("WIDG",), "WIDGET & SONS INC", None),
        "1067983": Company(("BRK.B",), "BERKSHIRE HATHAWAY INC", None),
    }  # BRK.B is BRK-B
    assert p.since == NOW - timedelta(hours=36) and p.known == frozenset()

    out = pull_8k_releases(warehouse, FakeSec([_feed(*ENTRIES)]), now=NOW)
    assert out["companies"] == 3 and out["landed"] == 2 and out["filings"] == 4
    assert out["cursor"] == _ny("2026-11-25T17:40:00-05:00").isoformat()
    with warehouse.connect(read_only=True) as con:
        landed = con.execute(
            "SELECT json_extract_string(payload, '$.accession_number'), json_extract_string(payload, '$.title')"
            " FROM raw.raw_news_articles ORDER BY 1"
        ).fetchall()
        links = con.execute("SELECT ticker FROM raw.news_ticker_sentiment ORDER BY 1").fetchall()
        mark = con.execute(
            "SELECT high_watermark FROM control.watermarks WHERE endpoint = ? AND dimension_key = ?",
            [CURSOR_ENDPOINT, CURSOR_DIMENSION],
        ).fetchone()
    assert landed == [
        (A_RESULTS, "Acme Corp Reports Third Quarter 2026 Results"),
        (W_DIRECTOR, "WIDGET & SONS INC: director or officer change"),
    ]
    assert links == [("ACME",), ("WIDG",)]
    assert mark == (out["cursor"],)

    rebuild_news_articles(warehouse)
    with warehouse.connect(read_only=True) as con:
        staged = con.execute(
            "SELECT provider, feed, items, tickers, source FROM staging.stg_news_articles"
            " ORDER BY published_at"
        ).fetchall()
    assert staged == [
        ("sec_edgar", "sec_8k", ["5.02"], ["WIDG"], "SEC filing"),
        ("sec_edgar", "sec_8k", ["2.02", "9.01"], ["ACME"], "SEC filing"),
    ]


def test_a_second_pull_reads_only_what_it_has_not_landed(warehouse):
    pull_8k_releases(warehouse, FakeSec([_feed(*ENTRIES)]), now=NOW)
    again = FakeSec([_feed(*ENTRIES)])
    assert pull_8k_releases(warehouse, again, now=NOW + timedelta(hours=1))["filings"] == 0
    assert again.calls == [("feed", 0)]
    # with the cursor held back, landed accessions still cost nothing; the
    # filing skipped as routine is looked at again
    with warehouse.connect() as con:
        con.execute("DELETE FROM control.watermarks WHERE endpoint = ?", [CURSOR_ENDPOINT])
    held = FakeSec([_feed(*ENTRIES)])
    out = pull_8k_releases(warehouse, held, now=NOW + timedelta(hours=1))
    assert out["landed"] == 0 and held.calls == [("feed", 0), ("page", _index_url(ACME, A_OTHER))]


def test_pull_with_no_company_mapped_says_so(tmp_path):
    wh = Warehouse(tmp_path / "empty.duckdb")
    wh.init_schema()
    client = FakeSec([_feed(*ENTRIES)])
    out = pull_8k_releases(wh, client, now=NOW)
    assert out["companies"] == 0 and "sec_company_tickers" in out["note"] and client.calls == []


def test_the_ticker_list_lands_as_one_snapshot(tmp_path):
    class Tickers:
        def __init__(self):
            self.calls = 0

        def company_tickers(self):
            self.calls += 1
            return {
                "0": {"cik_str": 1111, "ticker": "acme", "title": "ACME CORP"},
                "1": {"cik_str": 2222, "ticker": "WIDG", "title": "WIDGET & SONS INC"},
                "2": {"ticker": "NOCIK", "title": "dropped"},
            }

    wh = Warehouse(tmp_path / "tickers.duckdb")
    wh.init_schema()
    client = Tickers()
    engine = IngestEngine(wh, clients={Provider.SEC_EDGAR: client})
    first = engine.ingest_on_demand("sec_company_tickers", "sec_company_tickers", now=NOW)
    assert first.fetched and first.rows_written == 2
    again = engine.ingest_on_demand(
        "sec_company_tickers", "sec_company_tickers", now=NOW + timedelta(days=1)
    )
    assert not again.fetched and client.calls == 1  # within the 7-day TTL
    later = engine.ingest_on_demand(
        "sec_company_tickers", "sec_company_tickers", now=NOW + timedelta(days=8)
    )
    assert later.fetched and client.calls == 2
    with wh.connect(read_only=True) as con:
        tickers = con.execute(
            "SELECT ticker FROM raw.raw_sec_company_tickers ORDER BY 1"
        ).fetchall()
        marks = con.execute(
            "SELECT dimension_key FROM control.watermarks"
            " WHERE endpoint = 'raw.raw_sec_company_tickers'"
        ).fetchall()
    assert tickers == [("ACME",), ("WIDG",)]
    assert marks == [("sec_company_tickers",)]  # one for the list, not one per ticker


def test_a_new_ticker_list_drops_tickers_sec_no_longer_lists(tmp_path):
    wh = Warehouse(tmp_path / "tickers.duckdb")
    wh.init_schema()

    def rows(*tickers):
        return [
            {"ticker": t, "payload": {"cik_str": i, "ticker": t}} for i, t in enumerate(tickers)
        ]

    wh.land("raw_sec_company_tickers", rows("ACME", "GONE"), fetched_at=NOW, dimension_key="k")
    wh.land(
        "raw_sec_company_tickers",
        rows("ACME", "NEWCO", "NEWCO"),  # a repeated key keeps its last row
        fetched_at=NOW + timedelta(days=8),
        dimension_key="k",
    )
    with wh.connect(read_only=True) as con:
        tickers = con.execute(
            "SELECT ticker, payload->>'cik_str' FROM raw.raw_sec_company_tickers ORDER BY 1"
        ).fetchall()
    assert tickers == [("ACME", "0"), ("NEWCO", "2")]
