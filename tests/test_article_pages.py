"""Article pages for the news digest: robots.txt rules, the polite fetcher,
the per-story stop rule, retries, and staging the text, on a temporary
warehouse with a fake network (httpx.MockTransport)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from stockidence.ingest import articles
from stockidence.ingest.articles import (
    AI_OPTOUT,
    ALLOWED,
    DISALLOWED,
    UNREACHABLE,
    USER_AGENT,
    ArticleFetcher,
    StoryLinks,
    digests_to_read,
    fetch_digest_articles,
    fetch_stories,
    plan,
    retryable,
    user_agent_for,
)
from stockidence.staging import article_text
from stockidence.staging.article_text import (
    cap_words,
    drop_filing_cover,
    extract_text,
    rebuild_article_text,
    unwrap_filing,
)
from stockidence.storage import Warehouse

NOW = datetime(2026, 11, 20, 12, 30, tzinfo=UTC)

def _paragraph(i: int) -> str:
    # distinct on purpose: the extractor drops repeated paragraphs as boilerplate
    return (f"In the {i}th part of the report, the company said quarterly revenue rose {i + 10} percent "
            f"on demand for data center chips. Analysts at {i} banks had expected less, and the "
            f"shares gained {i}.5 percent in late trading after the forecast for region {i} went up.")


def _html(paragraphs: int = 6) -> str:
    body = "".join(f"<p>{_paragraph(i)}</p>" for i in range(paragraphs))
    return (f"<html><head><title>Story</title></head><body><nav>Home Markets</nav>"
            f"<article><h1>Chipmaker beats estimates</h1>{body}</article></body></html>")


ROBOTS_OPEN = "User-agent: *\nAllow: /\n"
ROBOTS_AI_OPTOUT = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"


class Net:
    """A fake internet: {url: response}; records every request."""

    def __init__(self, routes: dict[str, httpx.Response]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.routes.get(str(request.url), httpx.Response(404))

    def paths(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def _page(html: str = "", status: int = 200, ctype: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(status, text=html or _html(), headers={"content-type": ctype})


def _robots(text: str = ROBOTS_OPEN, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text)


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(round(s, 3))
        self.t += s


def _fetcher(net: Net, clock: Clock | None = None) -> ArticleFetcher:
    clock = clock or Clock()
    return ArticleFetcher(articles.new_client(httpx.MockTransport(net)), sleep=clock.sleep, clock=clock)


# --- rules -----------------------------------------------------------------

@pytest.mark.parametrize("robots, status, has_html, expected", [
    (ALLOWED, None, False, True),        # timeout, dropped connection
    (ALLOWED, 429, False, True),
    (ALLOWED, 503, False, True),
    (UNREACHABLE, None, False, True),    # robots.txt itself failed
    (ALLOWED, 403, False, False),        # a refusal is final
    (ALLOWED, 404, False, False),
    (DISALLOWED, None, False, False),
    (AI_OPTOUT, None, False, False),
    (ALLOWED, 200, True, False),         # came back, too thin: final
])
def test_retryable(robots, status, has_html, expected):
    assert retryable(robots, status, has_html) is expected


def test_cap_words_keeps_paragraphs_and_counts_the_whole_article():
    capped = cap_words("one two three\n\nfour five\nsix seven eight", limit=5)
    assert capped.text == "one two three\nfour five"
    assert capped.words == 8 and capped.truncated
    assert cap_words("a b\nc").truncated is False


def test_a_sign_in_form_is_not_taken_for_the_article():
    form = ("<form>" + "".join(f"<p>Continue with provider {i}. The password must contain at least "
                               f"{i} letters and one number to create an account.</p>" for i in range(12))
            + "</form>")
    page = _html().replace("<article>", form + "<article>")
    text = article_text.extract_text(page).text
    assert text.startswith("Chipmaker beats estimates") and "password" not in text


def test_digests_to_read_adds_the_weeks_dailies():
    built = [{"period": "weekly", "digest_date": "2026-11-20"}, {"period": "daily", "digest_date": "2026-11-20"}]
    keys = digests_to_read(built)
    assert keys[0] == ("weekly", date(2026, 11, 20))
    assert [d for p, d in keys if p == "daily"] == [date(2026, 11, 16) + timedelta(days=k) for k in range(5)]
    assert len(keys) == 6  # Friday's daily is not listed twice


# --- fetcher ---------------------------------------------------------------

def test_reads_an_allowed_page_with_an_honest_user_agent():
    net = Net({"https://a.com/robots.txt": _robots(), "https://a.com/story": _page()})
    page = _fetcher(net).fetch("https://a.com/story")
    assert page.robots == ALLOWED and page.http_status == 200 and page.readable
    assert all(r.headers["user-agent"] == USER_AGENT for r in net.requests)


@pytest.mark.parametrize("robots, verdict", [
    (_robots("User-agent: *\nDisallow: /\n"), DISALLOWED),
    (_robots(ROBOTS_AI_OPTOUT), AI_OPTOUT),
    (_robots("User-agent: ClaudeBot\nDisallow: /news/\n"), AI_OPTOUT),
    (_robots(status=403), DISALLOWED),
    (_robots(status=503), UNREACHABLE),
])
def test_robots_txt_decides_before_the_page_is_requested(robots, verdict):
    net = Net({"https://a.com/robots.txt": robots, "https://a.com/news/story": _page()})
    page = _fetcher(net).fetch("https://a.com/news/story")
    assert page.robots == verdict and not page.requested and page.html is None
    assert net.paths() == ["https://a.com/robots.txt"]


def test_missing_robots_txt_means_no_rules():
    net = Net({"https://a.com/story": _page()})  # robots.txt 404s
    assert _fetcher(net).fetch("https://a.com/story").readable


def test_robots_txt_is_asked_for_as_text_and_pages_as_html():
    # IIS answers a request whose Accept doesn't cover the file's type with a
    # 406, which would read as "no rules"
    def iis(request):
        accept = request.headers.get("accept", "")
        if request.url.path == "/robots.txt":
            if "text/plain" not in accept:
                return httpx.Response(406)
            return _robots("User-agent: *\nDisallow: /private/\n")
        return _page() if "text/html" in accept else httpx.Response(406)

    fetcher = ArticleFetcher(articles.new_client(httpx.MockTransport(iis)), sleep=lambda s: None)
    assert fetcher.fetch("https://a.com/private/story").robots == DISALLOWED
    assert fetcher.fetch("https://a.com/story").readable


def test_robots_txt_is_read_once_per_domain_and_requests_are_spaced():
    clock = Clock()
    net = Net({"https://a.com/robots.txt": _robots(), "https://a.com/1": _page(), "https://a.com/2": _page()})
    fetcher = _fetcher(net, clock)
    fetcher.fetch("https://a.com/1")
    fetcher.fetch("https://a.com/2")
    assert net.paths() == ["https://a.com/robots.txt", "https://a.com/1", "https://a.com/2"]
    assert clock.slept == [2.0, 2.0]  # the clock never moves between requests here


@pytest.mark.parametrize("response, outcome", [
    (_page(status=403), "http_403"),
    (_page(ctype="application/pdf"), "error"),
    (_page(html="<html><body><p>Subscribe to read.</p></body></html>"), "thin"),
])
def test_a_refusal_or_an_empty_page_is_not_readable(response, outcome):
    net = Net({"https://a.com/robots.txt": _robots(), "https://a.com/story": response})
    page = _fetcher(net).fetch("https://a.com/story")
    assert page.requested and not page.readable and page.outcome == outcome


def test_a_network_failure_is_recorded_not_raised():
    def boom(request):
        if request.url.path == "/robots.txt":
            return _robots()
        raise httpx.ConnectTimeout("timed out", request=request)

    fetcher = ArticleFetcher(articles.new_client(httpx.MockTransport(boom)), sleep=lambda s: None)
    page = fetcher.fetch("https://a.com/story")
    assert page.http_status is None and page.error.startswith("ConnectTimeout")
    assert retryable(page.robots, page.http_status, page.html is not None)


def test_a_redirect_is_held_to_the_new_domains_robots_txt():
    net = Net({
        "https://short.ly/robots.txt": _robots(),
        "https://short.ly/x": httpx.Response(301, headers={"location": "https://b.com/story"}),
        "https://b.com/robots.txt": _robots(ROBOTS_AI_OPTOUT),
        "https://b.com/story": _page(),
    })
    page = _fetcher(net).fetch("https://short.ly/x")
    assert page.robots == AI_OPTOUT and page.html is None and page.final_url == "https://b.com/story"


def test_a_story_stops_at_its_first_readable_page_and_at_three_tries():
    net = Net({
        "https://a.com/robots.txt": _robots(),
        **{f"https://a.com/{i}": _page(status=403) for i in range(5)},
        "https://b.com/robots.txt": _robots(),
        "https://b.com/0": _page(status=403),
        "https://b.com/1": _page(),
        "https://b.com/2": _page(),
    })
    fetcher = _fetcher(net)
    stories = [
        StoryLinks("daily", date(2026, 11, 20), 1, tuple(f"https://a.com/{i}" for i in range(5))),
        StoryLinks("daily", date(2026, 11, 20), 2, ("https://b.com/0", "https://b.com/1", "https://b.com/2")),
    ]
    pages = fetch_stories(fetcher, stories)
    assert [p.url for p in pages] == ["https://a.com/0", "https://a.com/1", "https://a.com/2",
                                      "https://b.com/0", "https://b.com/1"]


def test_robots_blocks_do_not_use_up_a_storys_tries():
    net = Net({
        "https://no.com/robots.txt": _robots("User-agent: *\nDisallow: /\n"),
        "https://a.com/robots.txt": _robots(),
        **{f"https://a.com/{i}": _page(status=403) for i in range(3)},
    })
    story = StoryLinks("daily", date(2026, 11, 20), 1,
                       ("https://no.com/1", "https://no.com/2", *(f"https://a.com/{i}" for i in range(3))))
    pages = fetch_stories(_fetcher(net), [story])
    assert sum(p.requested for p in pages) == 3 and len(pages) == 5


def test_the_run_stops_at_the_request_cap():
    net = Net({"https://a.com/robots.txt": _robots(), **{f"https://a.com/{i}": _page(status=403) for i in range(9)}})
    stories = [StoryLinks("daily", date(2026, 11, 20), r, (f"https://a.com/{r}",)) for r in range(9)]
    fetcher = _fetcher(net)
    assert len(fetch_stories(fetcher, stories, max_requests=4)) == 4
    assert fetcher.page_requests == 4


# --- plan, land, stage on a warehouse --------------------------------------

def _seed(wh: Warehouse, period: str, day: str, rank: int, urls: list[str]) -> None:
    """One picked story whose articles are `urls`, the first being the lead."""
    with wh.connect() as con:
        con.execute(
            "INSERT INTO mart.news_digest_stories (period, digest_date, rank, headline, url, published_at,"
            " n_articles, n_outlets, coverage, reaction, category, on_site, score)"
            " VALUES (?, ?, ?, 'Story', ?, '2026-11-20 10:00', ?, 1, 0, 0, 0, 0, 0)",
            [period, day, rank, urls[0], len(urls)])
        for i, url in enumerate(urls):
            aid = f"{period}-{day}-{rank}-{i}"
            con.execute("INSERT INTO mart.news_digest_articles VALUES (?, ?, ?, ?)", [period, day, rank, aid])
            con.execute(
                "INSERT OR REPLACE INTO staging.stg_news_articles (article_id, published_at, headline, url)"
                " VALUES (?, ?, 'x', ?)", [aid, f"2026-11-20 {9 - i:02d}:00", url])


@pytest.fixture
def wh(tmp_path):
    w = Warehouse(tmp_path / "pages.duckdb")
    w.init_schema()
    return w


def _rows(wh: Warehouse, sql: str) -> list[tuple]:
    with wh.connect(read_only=True) as con:
        return con.execute(sql).fetchall()


def test_plan_puts_the_lead_first_and_dedupes_across_digests(wh):
    # the lead (first url) was published last; the others earliest first
    _seed(wh, "daily", "2026-11-20", 1, ["https://a.com/lead", "https://b.com/x", "https://c.com/y"])
    _seed(wh, "weekly", "2026-11-20", 1, ["https://b.com/x", "https://d.com/z"])
    planned = plan(wh, [("weekly", date(2026, 11, 20)), ("daily", date(2026, 11, 20))], NOW)
    assert [s.urls for s in planned] == [
        ("https://a.com/lead", "https://c.com/y", "https://b.com/x"),
        ("https://d.com/z",),
    ]


def test_a_full_run_lands_pages_and_stages_text_once(wh):
    _seed(wh, "daily", "2026-11-20", 1, ["https://a.com/1", "https://a.com/2"])
    _seed(wh, "daily", "2026-11-20", 2, ["https://b.com/1"])
    net = Net({"https://a.com/robots.txt": _robots(), "https://a.com/1": _page(),
               "https://b.com/robots.txt": _robots(ROBOTS_AI_OPTOUT)})
    info = fetch_digest_articles(wh, [("daily", date(2026, 11, 20))], now=NOW, fetcher=_fetcher(net))
    assert info["stories"] == 2 and info["stories_read"] == 1 and info["page_requests"] == 1
    assert info["outcomes"] == {"readable": 1, AI_OPTOUT: 1} and info["skipped_domains"] == ["b.com"]
    assert _rows(wh, "SELECT url, robots, http_status, attempts FROM raw.news_article_pages ORDER BY 1") == [
        ("https://a.com/1", ALLOWED, 200, 1), ("https://b.com/1", AI_OPTOUT, None, 1)]

    assert rebuild_article_text(wh, now=NOW) == 1
    assert rebuild_article_text(wh, now=NOW) == 0  # incremental
    (words, truncated), = _rows(wh, "SELECT words, truncated FROM staging.stg_news_article_text")
    assert words >= articles.MIN_WORDS and not truncated

    # the read story and the opted-out page are not planned again
    assert plan(wh, [("daily", date(2026, 11, 20))], NOW + timedelta(days=1)) == []


def test_a_new_extractor_version_re_extracts(wh, monkeypatch):
    _seed(wh, "daily", "2026-11-20", 1, ["https://a.com/1"])
    net = Net({"https://a.com/robots.txt": _robots(), "https://a.com/1": _page()})
    fetch_digest_articles(wh, [("daily", date(2026, 11, 20))], now=NOW, fetcher=_fetcher(net))
    rebuild_article_text(wh, now=NOW)
    monkeypatch.setattr(article_text, "EXTRACTOR", "trafilatura 99")
    assert rebuild_article_text(wh, now=NOW) == 1


def test_a_transient_failure_waits_six_hours_and_gives_up_after_three_attempts(wh):
    _seed(wh, "daily", "2026-11-20", 1, ["https://a.com/1"])
    _seed(wh, "daily", "2026-11-20", 2, ["https://a.com/2"])
    net = Net({"https://a.com/robots.txt": _robots(),
               "https://a.com/1": _page(status=503), "https://a.com/2": _page(status=403)})
    key = [("daily", date(2026, 11, 20))]

    when = NOW
    for attempt in range(1, 4):
        fetch_digest_articles(wh, key, now=when, fetcher=_fetcher(net))
        assert plan(wh, key, when + timedelta(hours=5)) == []  # too soon to retry
        when += timedelta(hours=6)
    assert _rows(wh, "SELECT url, attempts FROM raw.news_article_pages ORDER BY 1") == [
        ("https://a.com/1", 3), ("https://a.com/2", 1)]  # the 403 was never retried
    assert plan(wh, key, when + timedelta(days=1)) == []  # three attempts: done


# --- SEC filings ------------------------------------------------------------

SEC_AGENT = "Test test@example.com"  # a stand-in for the real SEC_USER_AGENT, which .env may hold


def test_sec_gov_gets_the_sec_agent_and_the_rest_the_scrapers(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", SEC_AGENT)
    assert user_agent_for("www.sec.gov") == SEC_AGENT and user_agent_for("SEC.gov") == SEC_AGENT
    assert user_agent_for("www.reuters.com") == USER_AGENT
    monkeypatch.setenv("SEC_USER_AGENT", "")
    assert user_agent_for("www.sec.gov") == USER_AGENT


def test_the_fetcher_names_itself_to_sec_gov_as_sec_asks(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", SEC_AGENT)
    url = "https://www.sec.gov/Archives/edgar/data/1/2/ex99-1.htm"
    net = Net({"https://www.sec.gov/robots.txt": _robots(), url: _page(),
               "https://a.com/robots.txt": _robots(), "https://a.com/story": _page()})
    fetcher = _fetcher(net)
    assert fetcher.fetch(url).readable and fetcher.fetch("https://a.com/story").readable
    agents = {str(r.url): r.headers["user-agent"] for r in net.requests}
    assert agents == {"https://www.sec.gov/robots.txt": SEC_AGENT, url: SEC_AGENT,
                      "https://a.com/robots.txt": USER_AGENT, "https://a.com/story": USER_AGENT}


def test_unwrap_filing_reads_the_html_inside_edgars_envelope():
    inner = "<html><body><p>Acme reports results.</p></body></html>"
    wrapped = f"<DOCUMENT>\n<TYPE>EX-99.1\n<SEQUENCE>2\n<FILENAME>ex99-1.htm\n<TEXT>\n{inner}\n</TEXT>\n</DOCUMENT>"
    assert unwrap_filing(wrapped) == inner
    assert unwrap_filing(inner) == inner
    assert unwrap_filing("<p>no html tag</p>") == "<p>no html tag</p>"


COVER = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
FORM 8-K
CURRENT REPORT
ACME CORP
Indicate by check mark whether the registrant is an emerging growth company.
Emerging growth company
Item 2.02 Results of Operations and Financial Condition.
On November 25, 2026, Acme Corp issued a press release announcing its results.
Item 9.01 Financial Statements and Exhibits.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report.
By: /s/ Jane Doe"""


def test_an_8ks_cover_and_signatures_are_dropped():
    assert drop_filing_cover(COVER).splitlines() == [
        "Item 2.02 Results of Operations and Financial Condition.",
        "On November 25, 2026, Acme Corp issued a press release announcing its results.",
        "Item 9.01 Financial Statements and Exhibits."]


def test_without_the_check_boxes_the_8k_starts_at_its_first_item():
    text = COVER.replace("Indicate by check mark whether the registrant is an emerging growth company.\n", "")
    text = text.replace("Emerging growth company\n", "")
    assert drop_filing_cover(text).splitlines()[0] == "Item 2.02 Results of Operations and Financial Condition."


def test_other_text_is_left_as_it_is():
    release = "ACME CORP REPORTS RESULTS\nThe company said its Form 8-K filing has more.\nSignatures"
    assert drop_filing_cover(release) == release
    assert drop_filing_cover("") == ""


def test_extract_text_reads_an_enveloped_filing():
    body = "".join(f"<p>{_paragraph(i)}</p>" for i in range(4))
    wrapped = f"<DOCUMENT>\n<TYPE>EX-99.1\n<TEXT>\n<html><body><article>{body}</article></body></html>\n</TEXT>"
    text = extract_text(wrapped).text
    assert text.startswith("In the 0th part of the report") and "<TYPE>" not in text and "EX-99.1" not in text
