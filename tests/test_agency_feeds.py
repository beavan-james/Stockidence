"""Macro and policy stories from government release feeds: parsing RSS and
Atom, BLS's latest-numbers feed, naming tracked companies, and the pull
on a temporary warehouse. Fake clients stand in for the agencies' sites
and robots.txt: no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from stockidence.ingest.agency_feeds import (
    FEEDS,
    AgencyPlan,
    Feed,
    articles_from,
    bls_headline,
    bls_releases,
    name_patterns,
    named_tickers,
    parse_items,
    plan,
    pull_agency_releases,
    short_name,
)
from stockidence.ingest.articles import AI_OPTOUT, ALLOWED
from stockidence.ingest.clients.base import APIError
from stockidence.ingest.raw_mapping import article_id
from stockidence.staging.staging import rebuild_news_articles
from stockidence.storage import Warehouse

NOW = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
FED, BLS, SEC, FTC = FEEDS

FED_RSS = """﻿<?xml version="1.0" encoding="utf-8" ?>
<rss version="2.0"><channel><title>FRB: Press Release - Monetary Policy</title>
<item>
  <title>Minutes of the Board&#39;s discount rate meetings on October 19 and October 28, 2026</title>
  <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261124a.htm]]></link>
  <description><![CDATA[Minutes of the Board&#39;s discount rate meetings on October 19 and October 28, 2026]]></description>
  <pubDate><![CDATA[Tue, 24 Nov 2026 19:00:00 GMT]]></pubDate>
</item>
<item>
  <title>Federal Reserve issues FOMC statement</title>
  <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm]]></link>
  <description><![CDATA[Federal Reserve issues FOMC statement]]></description>
  <pubDate><![CDATA[Wed, 18 Nov 2026 19:00:00 GMT]]></pubDate>
</item>
<item>
  <title>Federal Reserve issues FOMC statement</title>
  <link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm]]></link>
  <description><![CDATA[Federal Reserve issues FOMC statement]]></description>
  <pubDate><![CDATA[Wed, 28 Oct 2026 18:00:00 GMT]]></pubDate>
</item>
</channel></rss>"""


def _bls_block(name, figure, code):
    return (
        f'<p>{name}:\t\t<br>\n\t<strong><span title="x" class="data">{figure}</span></strong><br>'
        f'\t<a href="https://www.bls.gov/news.release/{code}.toc.htm">News Release</a><br>\n'
        f'\t<a href="https://data.bls.gov/pdq/SurveyOutputServlet?series_id=X">Historical Data</a>\n</p>'
    )


def _bls_rss(*blocks):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<rss version="2.0"><channel>'
        "<title>Major Economic Indicators Latest Numbers</title><item>"
        "<title>Major Economic Indicators Latest Numbers</title><link>https://www.bls.gov/bls/</link>"
        f"<description><![CDATA[{''.join(blocks)}]]></description>"
        "<pubDate>Thu, 26 Nov 2026 13:30:00 GMT</pubDate></item></channel></rss>"
    )


BLS_OCT = (
    _bls_block("Consumer Price Index (CPI)", "+0.4%  in Oct 2026", "cpi"),
    _bls_block("Unemployment Rate", "4.1%  in Oct 2026", "empsit"),
    _bls_block("Payroll Employment", "+119,000(p)  in Oct 2026", "empsit"),
    _bls_block("Job Openings", "7.2 million(p)  in Sep 2026", "jolts"),
    "<p>Some heading with no figure</p>",
)
BLS_RSS = _bls_rss(*BLS_OCT)
# a month later: CPI is out for November, the rest unchanged
BLS_NOV = _bls_rss(
    _bls_block("Consumer Price Index (CPI)", "+0.2%  in Nov 2026", "cpi"), *BLS_OCT[1:]
)

SEC_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xml:base="https://www.sec.gov/"><channel><title>Press Releases</title>
<item>
  <title>    SEC Charges Kroger Executive with Insider Trading
</title>
  <link>https://www.sec.gov/newsroom/press-releases/2026-119-sec-charges-kroger-executive</link>
  <description>The Securities and Exchange Commission&amp;nbsp;today charged a former executive.</description>
  <pubDate>Wed, 25 Nov 2026 09:10:24 -0500</pubDate>
</item>
</channel></rss>"""

FTC_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>FTC competition</title>
<entry>
  <title>FTC Sues to Block Kroger&#8217;s Acquisition of Albertsons</title>
  <link href="https://www.ftc.gov/news-events/news/press-releases/2026/11/ftc-sues-block-kroger"/>
  <updated>2026-11-25T10:00:00-05:00</updated>
  <summary>&lt;p&gt;The Federal Trade Commission today sued to block the deal.&lt;/p&gt;</summary>
</entry>
<entry>
  <title>FTC Announces Annual Update of Size of Transaction Thresholds</title>
  <link href="https://www.ftc.gov/news-events/news/press-releases/2026/11/hsr-thresholds"/>
  <updated>2026-11-24T10:00:00-05:00</updated>
</entry>
</feed>"""

NAMES = name_patterns(
    [
        ("KR", "The Kroger Co."),
        ("ACI", "Albertsons Companies, Inc."),
        ("TGT", "Target Corp"),
        ("GPS", "Gap Inc"),
    ]
)


def _plan(known=(), bls_seen=False, names=NAMES):
    return AgencyPlan(known=frozenset(known), bls_seen=bls_seen, names=names)


# --- parsing ---------------------------------------------------------------


def test_parse_items_reads_rss():
    items = parse_items(FED_RSS.encode("utf-8"))
    assert [i["title"] for i in items][:2] == [
        "Minutes of the Board's discount rate meetings on October 19 and October 28, 2026",
        "Federal Reserve issues FOMC statement",
    ]
    assert (
        items[1]["link"]
        == "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm"
    )
    assert items[1]["published"] == datetime(2026, 11, 18, 19, 0, tzinfo=UTC)


def test_parse_items_reads_atom_and_trims_titles():
    ftc = parse_items(FTC_ATOM)
    assert ftc[0]["title"] == "FTC Sues to Block Kroger’s Acquisition of Albertsons"
    assert ftc[0]["link"].endswith("/ftc-sues-block-kroger")
    assert ftc[0]["published"] == datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
    assert parse_items(SEC_RSS)[0]["title"] == "SEC Charges Kroger Executive with Insider Trading"


def test_bls_latest_numbers_are_one_entry_per_release_and_period():
    releases = bls_releases(parse_items(BLS_RSS)[0]["description"])
    assert [(r["code"], r["period"], r["url"]) for r in releases] == [
        ("cpi", "Oct 2026", "https://www.bls.gov/news.release/cpi.nr0.htm"),
        ("empsit", "Oct 2026", "https://www.bls.gov/news.release/empsit.nr0.htm"),
        ("jolts", "Sep 2026", "https://www.bls.gov/news.release/jolts.nr0.htm"),
    ]
    assert releases[1]["indicators"] == [
        ("Unemployment Rate", "4.1%"),
        ("Payroll Employment", "+119,000(p)"),
    ]


def test_bls_headlines():
    cpi, empsit, jolts = bls_releases(parse_items(BLS_RSS)[0]["description"])
    assert bls_headline(cpi) == "Consumer Price Index, Oct 2026: Consumer Price Index (CPI) +0.4%"
    assert bls_headline(empsit) == (
        "The Employment Situation, Oct 2026: Unemployment Rate 4.1%; Payroll Employment +119,000(p)"
    )
    assert bls_headline(jolts) == "Job Openings: 7.2 million(p) in Sep 2026"  # a release not named


# --- naming companies ------------------------------------------------------


@pytest.mark.parametrize(
    "name, short",
    [
        ("NVIDIA Corp", "NVIDIA"),
        ("The Kroger Co.", "Kroger"),
        ("Albertsons Companies, Inc.", "Albertsons"),
        ("Alphabet Inc. Class A", "Alphabet"),
        ("Berkshire Hathaway Inc /DE/", "Berkshire Hathaway"),
        ("Procter & Gamble Co", "Procter & Gamble"),
        ("Inc", "Inc"),
    ],
)
def test_short_name(name, short):
    assert short_name(name) == short


def test_only_names_safe_to_look_for_are_matched():
    assert [t for _, t in NAMES] == ["KR", "ACI"]  # "Target" and "Gap" are everyday words
    assert named_tickers("FTC Sues to Block Kroger’s Acquisition of Albertsons", NAMES) == [
        "KR",
        "ACI",
    ]
    assert named_tickers("SEC charges Krogerville Bancorp", NAMES) == []
    assert named_tickers("Target practice", NAMES) == []


# --- articles from a feed --------------------------------------------------


def test_fed_releases_in_the_lookback_with_no_repeated_description():
    articles = articles_from(FED, FED_RSS, _plan(), NOW)
    assert [a["title"] for a in articles] == [
        "Minutes of the Board's discount rate meetings on October 19 and October 28, 2026",
        "Federal Reserve issues FOMC statement",
    ]  # the October statement is older than the lookback
    fomc = articles[1]
    assert fomc == {
        "article_id": article_id(fomc["url"]),
        "provider": "agencies",
        "feed": "fed",
        "title": "Federal Reserve issues FOMC statement",
        "ticker_sentiment": [],
        "source": "Federal Reserve",
        "summary": None,
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm",
        "time_published": "20261118T190000",
    }


def test_known_releases_are_not_landed_again():
    first = articles_from(FED, FED_RSS, _plan(), NOW)
    assert articles_from(FED, FED_RSS, _plan(known={a["article_id"] for a in first}), NOW) == []


def test_the_first_bls_run_lands_the_figures_out_as_an_undated_baseline():
    baseline = articles_from(BLS, BLS_RSS, _plan(), NOW)
    assert len(baseline) == 3
    assert all(a["baseline"] and "time_published" not in a for a in baseline)
    later = articles_from(
        BLS, BLS_NOV, _plan(known={a["article_id"] for a in baseline}, bls_seen=True), NOW
    )
    assert [(a["title"], a["period"], a["time_published"]) for a in later] == [
        (
            "Consumer Price Index, Nov 2026: Consumer Price Index (CPI) +0.2%",
            "Nov 2026",
            "20261126T133000",
        )
    ]
    assert "baseline" not in later[0]


def test_policy_releases_name_the_tracked_companies():
    ftc = articles_from(FTC, FTC_ATOM, _plan(), NOW)
    assert ftc[0]["ticker_sentiment"] == [{"ticker": "KR"}, {"ticker": "ACI"}]
    assert ftc[0]["summary"] == "The Federal Trade Commission today sued to block the deal."
    assert ftc[1]["ticker_sentiment"] == [] and ftc[1]["summary"] is None
    sec = articles_from(SEC, SEC_RSS, _plan(), NOW)
    assert sec[0]["ticker_sentiment"] == [{"ticker": "KR"}]
    assert (
        sec[0]["summary"]
        == "The Securities and Exchange Commission today charged a former executive."
    )
    # the Fed's releases are never matched against company names
    fed = articles_from(
        FED, FED_RSS.replace("FOMC statement", "FOMC statement on Kroger"), _plan(), NOW
    )
    assert all(a["ticker_sentiment"] == [] for a in fed)


# --- the pull on a warehouse ------------------------------------------------


class FakeFeeds:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls: list[str] = []

    def feed(self, url):
        self.calls.append(url)
        body = self.bodies[url]
        if isinstance(body, Exception):
            raise body
        return body


class FakeFetcher:
    """robots.txt verdicts by URL prefix, everything else allowed."""

    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}
        self.closed = False

    def verdict(self, url):
        return next((v for prefix, v in self.verdicts.items() if url.startswith(prefix)), ALLOWED)

    def close(self):
        self.closed = True


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "agencies.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        for ticker, name in (("KR", "The Kroger Co."), ("ACI", "Albertsons Companies, Inc.")):
            con.execute(
                "INSERT INTO staging.stg_prices_daily VALUES (?, '2026-11-24', 1, 1, 1, 1, 1, 0.0)",
                [ticker],
            )
            con.execute(
                "INSERT INTO raw.raw_company_profile VALUES (?, ?, ?)",
                [ticker, json.dumps({"name": name}), NOW],
            )
        # a profile for a stock without prices: not tracked, so never named
        con.execute(
            "INSERT INTO raw.raw_company_profile VALUES ('ZG', ?, ?)",
            [json.dumps({"name": "Zillow Group Inc"}), NOW],
        )
    return wh


def test_plan_names_the_tracked_companies(warehouse):
    p = plan(warehouse)
    assert [t for _, t in p.names] == ["ACI", "KR"] and not p.bls_seen and p.known == frozenset()


def test_pull_reads_each_allowed_feed_and_carries_on_past_a_failure(warehouse):
    client = FakeFeeds(
        {
            FED.url: FED_RSS,
            BLS.url: BLS_RSS,
            SEC.url: SEC_RSS,
            FTC.url: APIError("HTTP 503 from www.ftc.gov"),
        }
    )
    fetcher = FakeFetcher({"https://www.sec.gov/": AI_OPTOUT})
    out = pull_agency_releases(warehouse, client, now=NOW, fetcher=fetcher)
    assert out == {
        "landed": 5,
        "baseline": 3,
        "requests": 2,
        "feeds": {
            "fed": "2 new",
            "bls": "3 new",
            "sec_press": f"skipped ({AI_OPTOUT})",
            "ftc": "failed (APIError)",
        },
    }
    assert client.calls == [FED.url, BLS.url, FTC.url]  # the SEC's robots.txt said no
    assert not fetcher.closed  # the caller's fetcher is the caller's to close

    rebuild_news_articles(warehouse)
    with warehouse.connect(read_only=True) as con:
        staged = con.execute(
            "SELECT provider, feed, source, headline FROM staging.stg_news_articles"
            " ORDER BY published_at"
        ).fetchall()
    # the BLS baseline is landed but never staged
    assert staged == [
        ("agencies", "fed", "Federal Reserve", "Federal Reserve issues FOMC statement"),
        (
            "agencies",
            "fed",
            "Federal Reserve",
            "Minutes of the Board's discount rate meetings on October 19 and October 28, 2026",
        ),
    ]

    later = NOW + timedelta(days=1)
    client = FakeFeeds({FED.url: FED_RSS, BLS.url: BLS_NOV, SEC.url: SEC_RSS, FTC.url: FTC_ATOM})
    again = pull_agency_releases(warehouse, client, now=later, fetcher=FakeFetcher())
    assert again["feeds"] == {"fed": "0 new", "bls": "1 new", "sec_press": "1 new", "ftc": "2 new"}
    assert again["baseline"] == 0
    with warehouse.connect(read_only=True) as con:
        links = con.execute(
            "SELECT ticker, COUNT(*) FROM raw.news_ticker_sentiment GROUP BY 1 ORDER BY 1"
        ).fetchall()
    assert links == [("ACI", 1), ("KR", 2)]


def test_pull_closes_a_fetcher_it_made(warehouse, monkeypatch):
    made = []

    class Own(FakeFetcher):
        def __init__(self):
            super().__init__({"https://": AI_OPTOUT})
            made.append(self)

    monkeypatch.setattr("stockidence.ingest.agency_feeds.ArticleFetcher", Own)
    out = pull_agency_releases(
        warehouse, FakeFeeds({}), now=NOW, feeds=(Feed("fed", "Federal Reserve", FED.url),)
    )
    assert out["landed"] == 0 and made[0].closed
