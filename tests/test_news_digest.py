"""News digests: daily and weekly windows, filters, grouping, events and
scoring, staging, the mart build and the read API, on a temporary
warehouse."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime, timedelta

import pytest

from stockidence.mart.news_digest import (
    DAILY,
    MARKET,
    MIN_PICK_SCORE,
    WEEKLY,
    Article,
    Story,
    agency_event,
    article_categories,
    build_daily_digest,
    build_weekly_digest,
    categories_of,
    digest_window,
    group_stories,
    headline_words,
    item_event,
    latest_digest_date,
    latest_weekly_date,
    market_wide,
    not_news,
    pick_context,
    pick_stories,
    routine_items,
    score_context,
    score_story,
    size_score,
    weekly_window,
)
from stockidence.staging.staging import rebuild_news_articles
from stockidence.storage import Warehouse


def _article(
    aid,
    headline,
    *,
    hours=0,
    source="Reuters",
    tickers=(),
    feed=None,
    items=(),
    summary=None,
    base=datetime(2026, 8, 25, 14),
):
    return Article(
        article_id=aid,
        published_at=base + timedelta(hours=hours),
        source=source,
        headline=headline,
        summary=summary,
        url=f"https://x/{aid}",
        tickers=tuple(tickers),
        words=headline_words(headline),
        categories=article_categories(headline, feed, items, summary),
        feed=feed,
        items=tuple(items),
    )


# --- window ----------------------------------------------------------------


def test_window_runs_07_to_07_new_york_in_utc():
    # Tue Aug 25 2026 (EDT, UTC-4): Mon 07:00 ET to Tue 07:00 ET
    assert digest_window(date(2026, 8, 25)) == (
        datetime(2026, 8, 24, 11),
        datetime(2026, 8, 25, 11),
    )


def test_monday_window_covers_the_weekend():
    start, end = digest_window(date(2026, 8, 24))
    assert start == datetime(2026, 8, 21, 11) and end == datetime(2026, 8, 24, 11)


def test_window_follows_standard_time():
    # Tue Nov 17 2026 (EST, UTC-5)
    assert digest_window(date(2026, 11, 17)) == (
        datetime(2026, 11, 16, 12),
        datetime(2026, 11, 17, 12),
    )


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 8, 25, 10, 59, tzinfo=UTC), date(2026, 8, 24)),  # 06:59 ET Tue
        (datetime(2026, 8, 25, 11, 0, tzinfo=UTC), date(2026, 8, 25)),  # 07:00 ET Tue
        (datetime(2026, 8, 29, 15, 0, tzinfo=UTC), date(2026, 8, 28)),  # Saturday
        (datetime(2026, 8, 31, 10, 0, tzinfo=UTC), date(2026, 8, 28)),  # Mon before 07:00
    ],
)
def test_latest_digest_date(now, expected):
    assert latest_digest_date(now) == expected


def test_weekly_window_runs_saturday_to_saturday_07_new_york():
    # dated Fri Aug 28 2026 (EDT): Sat Aug 22 07:00 ET to Sat Aug 29 07:00 ET
    assert weekly_window(date(2026, 8, 28)) == (
        datetime(2026, 8, 22, 11),
        datetime(2026, 8, 29, 11),
    )


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 11, 21, 11, 59, tzinfo=UTC), date(2026, 11, 13)),  # Sat 06:59 EST
        (datetime(2026, 11, 21, 12, 0, tzinfo=UTC), date(2026, 11, 20)),  # Sat 07:00 EST
        (datetime(2026, 11, 22, 15, 0, tzinfo=UTC), date(2026, 11, 20)),  # Sunday
        (datetime(2026, 11, 20, 23, 0, tzinfo=UTC), date(2026, 11, 13)),  # Friday evening
    ],
)
def test_latest_weekly_date(now, expected):
    assert latest_weekly_date(now) == expected


# --- filters ---------------------------------------------------------------


@pytest.mark.parametrize(
    "headline",
    [
        "Vanguard Group Inc. Takes Position in Apple Inc. $AAPL",
        "Acme Capital LLC Has $1.2 Million Stake in Deere & Company $DE",
        "Intuit CFO Sells 16,524 Shares of Stock",
        "Goldman Sachs Raises Nvidia Price Target to $250",
        "Brown & Brown Inc. stock underperforms Tuesday when compared to competitors",
        "Synopsys Inc. stock outperforms competitors on strong trading day",
        "Evolve Private Wealth LLC Purchases New Position in The PNC Financial Services Group, Inc $PNC",
        "Ieq Capital LLC Takes $9.78 Million Position in Dollar Tree, Inc. $DLTR",
        "Maxi Investments CY Ltd Buys New Shares in Salesforce Inc. $CRM",
        "Medtronic (MDT) Stock Dips While Market Gains: Key Facts",
        "Bronstein, Gewirtz & Grossman LLC Urges Intuit Inc. Investors to Act: Class Action Filed",
        "PODD Shareholder Alert: August 31, 2026 Lead Plaintiff Deadline in Insulet Class Action",
        "Apple to Present at Goldman Sachs Communacopia Conference",
        "Rollins Inc stock hits 52-week low at 35.31 USD By Investing.com",
        "Copart stock may move 6.2% on Sept. 10 earnings release",
        "INTEL CORPORATION - COMMON STOCK - Nancy Pelosi Congressional Trade on Jul. 24, 2026",
        "Donald Trump - Salesforce Inc. Trump Trade on Jun. 18, 2026",
    ],
)
def test_routine_headlines_are_dropped(headline):
    assert not_news(headline) == "routine"


@pytest.mark.parametrize(
    "headline",
    [
        "Is Nvidia Stock a Buy Now?",
        "3 Growth Stocks to Buy in September",
        "Cramer says this chip stock is a winner",
    ],
)
def test_opinion_headlines_are_dropped(headline):
    assert not_news(headline) == "commentary"


@pytest.mark.parametrize(
    "headline",
    [
        "Intuit stock slides after Q4 earnings beat is followed up by soft guidance",
        "Nvidia to buy Hugging Face for $13 billion in big bet on open AI models",
        "Walmart promises price cuts after $2.9B tariff refund",
        "Fed holds rates steady as inflation cools",
        "JPMorgan beats estimates as trading revenue jumps",
    ],
)
def test_news_headlines_are_kept(headline):
    assert not_news(headline) is None


# --- categories ------------------------------------------------------------


@pytest.mark.parametrize(
    "headline",
    [
        "FTC Challenges Amgen’s Bid to Shield Enbrel Patent Deal",
        "DOJ expands beef price investigation to Kroger, Walmart, Costco and other major retailers",
        "Deckers Wins Dismissal of Antitrust Suit Over ‘Sham’ Ugg Cases",
        "SEC clears VerifyMe-OpenWorld merger for shareholder vote",
        "US Senators Urge SEC Probe Into Trump Media’s Preferential Truth Social Access Plan",
        "Goldman Sachs Exits XRP ETF as Senate Stalls CLARITY Act",
        "House Democrats Say Rail Merger Review Must Prioritize Workers",
        "Pacific Gas & Electric Stock Slides As California Lawmakers Block Key Wildfire Insurance Reform",
        "Nvidia chief to testify before Congress on chip sales to China",
        "Micron shares rise as White House pushes Apple away from Chinese memory chips",
        "President signs executive order on AI data centers",
        "Trump Threatens Comcast and Disney: President Says Their Licenses Could Be at Risk",
        "UK fines Citigroup unit over Russia sanctions breaches",
        "SMCI Clears Senior Management In Export Control Investigation",
    ],
)
def test_government_action_is_policy(headline):
    assert "policy" in categories_of(headline)


@pytest.mark.parametrize(
    "headline",
    [
        # a company's filings with the SEC, not the SEC acting
        "Apple Inc. SEC Filing (Aug 11, 2026)",
        "LYNX SEC Filings - Lyntris Inc. 10-K, 10-Q, 8-K Forms",
        "Agnico Eagle Mines (NYSE: AEM) files SEC report",
        "Gerdau Files Mid‑Year 2026 Interim Financials with U.S. SEC",
        "Lumexa Imaging Holdings Reports Q2 2026 Financial Results in SEC 8-K Filing",
        # bills, houses and congresses that aren't Congress
        "Bill Ackman Exits Alphabet, Raises Bets on Microsoft & Meta",
        "Becton Dickinson (NYSE: BDX) withholds 1,049 shares for CRO’s tax bill",
        "Bristol Myers Squibb (BMY) Unveils Five Year Camzyos Data At ESC Congress",
        "Avalyn Announces Multiple Presentations at the European Respiratory Society International Congress 2026",
        "Thomson Reuters launches in-house AI model to cut Anthropic costs",
        # Trump's businesses and family, not the White House
        "Trump Media Posts $238 Million Quarterly Loss",
        "Eric Trump-backed Space-Eyes to go public in $638 million SPAC deal",
    ],
)
def test_lookalikes_are_not_policy(headline):
    assert "policy" not in categories_of(headline)


@pytest.mark.parametrize(
    "headline, macro",
    [
        ("Fed holds rates steady as inflation cools", True),
        ("UBS forecasts two US Fed rate hikes in 2026 after strong jobs report", True),
        ("Trump Sets 50% Auto Tariffs on Canada", True),
        ("'We're fed up': Portsmouth family wants action on overgrown cell tower property", False),
        ("Clean energy groups call on regulators to reject We Energies rate hike", False),
        ("Coca-Cola’s Tax Rate Cut Just Boosted 2026 Earnings Guidance", False),
    ],
)
def test_macro_is_the_economy_not_its_words_elsewhere(headline, macro):
    assert ("macro" in categories_of(headline)) is macro


# --- grouping --------------------------------------------------------------


def test_same_stock_same_category_is_one_story_whatever_the_words():
    a = _article("1", "Broadcom Q3 revenue tops estimates on AI demand", tickers=["AVGO"])
    b = _article(
        "2", "Broadcom shares rise after strong quarterly results", hours=2, tickers=["AVGO"]
    )
    c = _article("3", "Oracle signs cloud deal with OpenAI", hours=1, tickers=["ORCL"])
    groups = group_stories([a, b, c])
    assert sorted(sorted(x.article_id for x in g) for g in groups) == [["1", "2"], ["3"]]


def test_shared_distinctive_words_group_across_outlets():
    a = _article("1", "Nvidia to buy Hugging Face for $13 billion", tickers=["NVDA"])
    b = _article(
        "2",
        "Nvidia agrees to acquire Hugging Face in $13 billion deal",
        hours=1,
        source="Bloomberg",
        tickers=["NVDA"],
    )
    filler = [
        _article(str(i), f"Unrelated company {i} opens new plant", hours=3, tickers=[f"X{i}"])
        for i in range(3, 8)
    ]
    groups = group_stories([a, b, *filler])
    assert any({x.article_id for x in g} == {"1", "2"} for g in groups)


def test_articles_far_apart_are_not_merged():
    a = _article("1", "Broadcom Q3 revenue tops estimates", tickers=["AVGO"])
    b = _article("2", "Broadcom Q3 revenue tops estimates", hours=48, tickers=["AVGO"])
    assert len(group_stories([a, b])) == 2


# --- events ----------------------------------------------------------------


@pytest.mark.parametrize(
    "items, released, routine",
    [
        (["9.01"], None, True),  # exhibits only
        (["5.07"], None, True),  # vote results
        (["5.03", "9.01"], None, True),  # a bylaw change
        (["1.01", "2.03", "9.01"], None, True),  # a credit agreement and the debt it creates
        (["2.03", "5.07"], None, True),
        (["1.01"], None, False),  # an agreement alone may be a deal
        (["2.02", "9.01"], None, False),
        (["8.01", "9.01"], None, False),  # news only with a press release
        (["8.01", "9.01"], True, False),
        (["8.01", "9.01"], False, True),
        (["7.01", "5.07"], False, True),
        (["7.01", "2.02"], False, False),
    ],
)
def test_routine_items(items, released, routine):
    assert routine_items(items, released) == routine


@pytest.mark.parametrize(
    "items, text, event",
    [
        (["1.03"], "", 1.0),
        (["2.02", "9.01"], "Intuit Reports Fourth-Quarter Fiscal 2026 Results", 0.7),
        (["2.02", "4.02"], "", 0.9),  # the best item
        (["1.01"], "Acme to acquire Widget Co for $4 billion", 0.9),
        (["1.01"], "Acme enters into a revolving credit agreement", 0.2),
        (["5.02"], "Acme names Jane Doe chief executive officer", 0.6),
        (["5.02"], "Acme CFO to retire at year end", 0.6),
        (["5.02"], "A director will not stand for re-election", 0.1),
        (["1.05"], "", 0.2),  # an item not listed
        (["9.01"], "", 0.0),
    ],
)
def test_item_event(items, text, event):
    assert item_event(items, text) == event


@pytest.mark.parametrize(
    "feed, headline, tickers, event",
    [
        ("fed", "Federal Reserve issues FOMC statement", (), 1.0),
        ("fed", "Minutes of the Federal Open Market Committee, October 27-28, 2026", (), 0.8),
        (
            "fed",
            "Minutes of the Board's discount rate meetings on October 19 and October 28, 2026",
            (),
            0.2,
        ),
        (
            "fed",
            (
                "Federal Reserve announces revised tentative schedule of Federal Open Market "
                "Committee meetings in 2027"
            ),
            (),
            0.2,
        ),
        ("bls", "Consumer Price Index, Oct 2026: CPI +0.4%", (), 1.0),
        (
            "bls",
            "The Employment Situation, Oct 2026: Unemployment Rate 4.1%; Payrolls +119,000",
            (),
            1.0,
        ),
        ("bls", "Producer Price Index, Oct 2026: PPI +0.2%", (), 0.8),
        ("bls", "Productivity and Costs, Q3 2026: Productivity +1.9%", (), 0.4),
        ("ftc", "FTC Sues to Block Kroger's Acquisition of Albertsons", ("KR",), 0.8),
        (
            "ftc",
            "FTC Sues to Block Kroger's Acquisition of Albertsons",
            (),
            0.4,
        ),  # no listed company named
        ("ftc", "FTC Announces Hart-Scott-Rodino Thresholds for 2027", ("KR",), 0.4),
        ("sec_press", "SEC Adopts Final Rules on Fund Names", (), 0.5),
        ("sec_press", "SEC Charges Acme Corp with Accounting Fraud", ("ACME",), 0.5),
        ("sec_press", "SEC Charges Investment Adviser with Fraud", (), 0.2),
        ("sec_press", "SEC Announces Agenda for Investor Advisory Committee Meeting", (), 0.2),
    ],
)
def test_agency_event(feed, headline, tickers, event):
    assert agency_event(feed, headline, tickers) == event


@pytest.mark.parametrize(
    "cap, size",
    [
        (None, 0.0),
        (0, 0.0),
        (5e9, 0.0),
        (1e10, 0.0),
        (1e11, 0.5),
        (1e12, 1.0),
        (3e12, 1.0),
    ],
)
def test_size_is_log_scaled_from_10bn_to_1tn(cap, size):
    assert size_score(cap) == pytest.approx(size)


@pytest.mark.parametrize(
    "headline, feed, items, summary, categories",
    [
        ("Federal Reserve issues FOMC statement", "fed", (), None, ("macro",)),
        ("SEC Charges Investment Adviser with Fraud", "sec_press", (), None, ("policy",)),
        (
            "FTC Sues to Block Kroger's Acquisition of Albertsons",
            "ftc",
            (),
            None,
            ("deal", "policy"),
        ),
        (
            "Intuit Reports Fourth-Quarter Fiscal 2026",
            "sec_8k",
            ("2.02", "9.01"),
            None,
            ("earnings",),
        ),
        ("Acme Completes Sale of Its Pipeline Unit", "sec_8k", ("2.01", "9.01"), None, ("deal",)),
        (
            "Acme Corp: material agreement",
            "sec_8k",
            ("1.01",),
            "Acme agreed to be acquired by Widget for $40 a share in cash.",
            ("deal",),
        ),
        (
            "Acme Corp: material agreement",
            "sec_8k",
            ("1.01",),
            "Acme entered into a credit agreement with its lenders.",
            (),
        ),
    ],
)
def test_categories_come_from_the_source_too(headline, feed, items, summary, categories):
    assert article_categories(headline, feed, items, summary) == categories


@pytest.mark.parametrize(
    "feed, event, whole",
    [
        ("fed", 1.0, True),
        ("bls", 0.4, True),
        ("fed", 0.2, False),  # a meeting schedule, discount-rate minutes
        ("sec_press", 0.5, False),
        ("ftc", 0.8, False),
        ("sec_8k", 1.0, False),
    ],
)
def test_only_fed_and_bls_releases_of_weight_are_market_wide(feed, event, whole):
    assert market_wide(_article("a", "x", feed=feed), event) is whole


# --- scoring ---------------------------------------------------------------


def _filing_article(aid, headline, items, tickers, **kw):
    return _article(
        aid, headline, feed="sec_8k", items=items, tickers=tickers, source="SEC filing", **kw
    )


def test_score_is_the_weighted_sum():
    a = _filing_article(
        "r", "Intuit Reports Fourth-Quarter Fiscal 2026 Results", ("2.02", "9.01"), ["INTU"]
    )
    s = score_story([a], {"INTU": -0.10}, {"INTU"}, sizes={"INTU": 1e12})
    assert s.inputs == {"event": 0.7, "reaction": 1.0, "size": 1.0, "on_site": 1.0}
    assert s.score == pytest.approx(0.40 * 0.7 + 0.25 + 0.20 + 0.15)
    assert (s.move_ticker, s.move_return) == ("INTU", -0.10)


def test_the_release_with_the_biggest_event_leads():
    results = _filing_article(
        "r", "Intuit Reports Fourth-Quarter Fiscal 2026 Results", ("2.02", "9.01"), ["INTU"]
    )
    follow_up = _filing_article(
        "f", "Intuit Inc.: Regulation FD disclosure", ("7.01", "9.01"), ["INTU"], hours=1
    )
    s = score_story([follow_up, results], {}, set())
    assert s.lead is results and s.inputs["event"] == 0.7


def test_reaction_is_the_lead_stocks_move_not_a_co_named_one():
    arts = [
        _article("1", "Walmart promises price cuts after tariff refund", tickers=["WMT", "TGT"]),
        _article(
            "2",
            "Walmart to cut prices with tariff refund",
            hours=1,
            source="CNBC",
            tickers=["WMT", "TGT"],
        ),
    ]
    s = score_story(arts, {"WMT": -0.001, "TGT": 0.045}, ranked=set())
    assert s.move_ticker == "WMT"
    assert s.inputs["reaction"] == pytest.approx(0.01)


def test_no_price_for_the_lead_stock_scores_no_reaction_not_the_markets():
    arts = [
        _article(
            "1",
            "SEC Charges Valley National with Fraud",
            feed="sec_press",
            tickers=["VLYPN", "WMT"],
        )
    ]
    s = score_story(arts, {"WMT": 0.05}, ranked=set(), market=0.02)
    assert s.move_ticker is None and s.inputs["reaction"] == 0.0


def test_size_is_the_lead_stocks_market_cap():
    a = _filing_article("r", "Acme Reports Results", ("2.02",), ["ACME", "MEGA"])
    s = score_story([a], {}, set(), sizes={"ACME": 1e11, "MEGA": 3e12})
    assert s.inputs["size"] == pytest.approx(0.5)
    assert score_story([a], {}, set()).inputs["size"] == 0.0  # no profile: no size


def test_a_fed_decision_takes_the_markets_move_and_full_size():
    a = _article("f", "Federal Reserve issues FOMC statement", feed="fed", source="Federal Reserve")
    s = score_story([a], {}, set(), market=-0.015)
    assert (s.move_ticker, s.move_return) == (MARKET, -0.015)
    assert s.inputs == {"event": 1.0, "reaction": pytest.approx(0.75), "size": 1.0, "on_site": 0.0}
    assert s.score == pytest.approx(0.40 + 0.25 * 0.75 + 0.20)
    assert score_story([a], {}, set(), WEEKLY, market=-0.015).inputs["reaction"] == pytest.approx(
        0.375
    )


def test_a_minor_fed_release_is_not_market_wide():
    a = _article(
        "m", "Minutes of the Board's discount rate meetings on August 10, 2026", feed="fed"
    )
    s = score_story([a], {}, set(), market=0.02)
    assert s.move_ticker is None and s.inputs["reaction"] == 0.0 and s.inputs["size"] == 0.0
    assert s.score < MIN_PICK_SCORE


def test_same_outlet_under_two_names_counts_once():
    arts = [
        _article("1", "Fed holds rates", source="Investing.com"),
        _article("2", "Fed holds rates steady", source="Investing.com Canada"),
    ]
    assert score_story(arts, {}, set()).n_outlets == 1


# --- market context --------------------------------------------------------


def test_context_coverage_is_log_scaled_by_outlet_and_capped():
    def story(n, period=DAILY):
        return score_context(
            [
                _article(str(i), "Stocks rally as Fed holds rates", source=f"Outlet{i}")
                for i in range(n)
            ],
            period,
        )

    assert story(1).score == 0.0
    assert story(2).score == pytest.approx(1 / 3)
    assert story(8).score == 1.0
    assert story(12).score == 1.0
    assert story(8, WEEKLY).score < 1.0 and story(12, WEEKLY).score == 1.0


def test_context_keeps_the_most_covered_few():
    groups = [
        [_article(f"{k}-{i}", f"Headline {k}", source=f"Outlet{i}") for i in range(k)]
        for k in range(1, 9)
    ]
    picked = pick_context(groups, DAILY)
    assert [s.n_outlets for s in picked] == [8, 7, 6, 5, 4]
    assert len(pick_context(groups, WEEKLY)) == 8


# --- picking ---------------------------------------------------------------


def _story(aid, score, *categories):
    a = _article(aid, f"Story {aid}")
    return Story(
        articles=(a,),
        lead=a,
        tickers=(),
        categories=categories,
        n_outlets=1,
        move_ticker=None,
        move_return=None,
        inputs={},
        score=score,
    )


def _day(n_other=12, policy_scores=()):
    """A ranked day: other stories scoring 0.90 down by 0.03 each, then
    policy and macro stories (alternating) below all of them."""
    others = [_story(f"o{i}", 0.90 - 0.03 * i, "earnings") for i in range(n_other)]
    kinds = ("policy", "macro")
    below = [_story(f"p{i}", s, kinds[i % 2]) for i, s in enumerate(policy_scores)]
    return others + below


def _ids(stories):
    return [s.lead.article_id for s in stories]


def test_a_story_under_the_floor_is_not_picked():
    ranked = [_story("a", 0.50), _story("b", 0.21), _story("c", 0.19)]
    assert _ids(pick_stories(ranked, DAILY)) == ["a", "b"]


@pytest.mark.parametrize(
    "policy_scores, picked",
    [
        ((), []),  # none that day: the top 10 on score
        ((0.32,), ["p0"]),  # one: it takes the 10th place
        ((0.32, 0.31, 0.30), ["p0", "p1"]),  # three: the best two take the 9th and 10th
    ],
)
def test_a_day_keeps_up_to_two_places_for_policy_and_macro(policy_scores, picked):
    ranked = _day(policy_scores=policy_scores)
    picks = pick_stories(ranked, DAILY)
    others = [f"o{i}" for i in range(10 - len(picked))]
    assert _ids(picks) == others + picked


def test_policy_already_in_the_top_ten_counts_toward_the_two():
    ranked = _day(policy_scores=(0.32, 0.31))
    ranked.insert(3, _story("top", 0.80, "earnings", "policy"))
    picks = pick_stories(ranked, DAILY)
    assert _ids(picks) == ["o0", "o1", "o2", "top", "o3", "o4", "o5", "o6", "o7", "p0"]
    ranked.insert(5, _story("top2", 0.75, "macro"))
    assert pick_stories(ranked, DAILY) == ranked[:10]


def test_a_reserved_place_needs_more_than_the_category():
    rule = score_story(
        [_article("s", "SEC Adopts Final Rules on Fund Names", feed="sec_press", source="SEC")],
        {},
        set(),
    )
    challenge = score_story(
        [
            _article(
                "f",
                "FTC Sues to Block Kroger's Acquisition of Albertsons",
                feed="ftc",
                source="FTC",
                tickers=["KR"],
            )
        ],
        {},
        set(),
    )
    assert rule.categories == ("policy",) and rule.score == pytest.approx(0.20)
    assert challenge.score == pytest.approx(0.32)
    others = _day()
    assert pick_stories([*others, rule], DAILY) == others[:10]
    assert pick_stories([*others, challenge], DAILY)[-1] is challenge


def test_a_short_day_keeps_everything_and_a_week_keeps_no_places():
    short = _day(n_other=6, policy_scores=(0.20,))
    assert pick_stories(short, DAILY) == short
    week = _day(n_other=16, policy_scores=(0.32, 0.31))
    assert pick_stories(week, WEEKLY) == week[:15]


# --- staging, build, API on a temp warehouse -------------------------------

T0 = "2026-08-25 23:00:00+00"


def _land(con, aid, payload, fetched_at=T0):
    con.execute(
        "INSERT INTO raw.raw_news_articles VALUES (?, ?, ?)",
        [aid, json.dumps(payload), fetched_at],
    )


def _slug(title):
    return re.sub(r"\W+", "-", title.lower()).strip("-")


def _finnhub(title, ts, related, source="Reuters", category="general"):
    return {
        "headline": title,
        "title": title,
        "time_published": ts,
        "source": source,
        "category": category,
        "summary": f"{title}.",
        "url": f"https://news/{_slug(title)}-{source}",
        "ticker_sentiment": [{"ticker": t} for t in related],
    }


def _filing(title, ts, tickers, items, summary=None):
    return {
        "provider": "sec_edgar",
        "feed": "sec_8k",
        "title": title,
        "time_published": ts,
        "ticker_sentiment": [{"ticker": t} for t in tickers],
        "source": "SEC filing",
        "summary": summary,
        "url": f"https://www.sec.gov/Archives/{_slug(title)}.htm",
        "items": items,
        "form": "8-K",
    }


def _release(feed, source, title, ts, tickers=(), **extra):
    payload = {
        "provider": "agencies",
        "feed": feed,
        "title": title,
        "source": source,
        "ticker_sentiment": [{"ticker": t} for t in tickers],
        "summary": None,
        "url": f"https://{feed}.example.gov/{_slug(title)}",
        **extra,
    }
    if ts:
        payload["time_published"] = ts
    return payload


@pytest.fixture
def warehouse(tmp_path):
    """Wednesday Aug 26 2026's digest: the 24 hours from Tuesday 11:00 UTC
    (07:00 ET), with Tuesday's session for the moves."""
    wh = Warehouse(tmp_path / "digest.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        # stories: two 8-Ks and three agency releases
        _land(
            con,
            "intu",
            _filing(
                "Intuit Reports Fourth-Quarter Fiscal 2026 Results",
                "20260825T201500",
                ["INTU"],
                ["2.02", "9.01"],
                "Intuit Inc. announced financial results for its fourth quarter.",
            ),
        )
        _land(
            con,
            "aapl",
            _filing(
                "Apple Inc.: director or officer change",
                "20260825T213000",
                ["AAPL"],
                ["5.02"],
                "A member of the Board informed the company that she will "
                "not stand for re-election.",
            ),
        )
        _land(
            con,
            "fomc",
            _release(
                "fed", "Federal Reserve", "Federal Reserve issues FOMC statement", "20260825T180000"
            ),
        )
        _land(
            con,
            "disc",
            _release(
                "fed",
                "Federal Reserve",
                "Minutes of the Board's discount rate meetings on July 20 and July 29, 2026",
                "20260825T190000",
            ),
        )
        _land(
            con,
            "secp",
            _release(
                "sec_press",
                "SEC",
                "SEC Charges Investment Adviser with Defrauding Clients",
                "20260825T160000",
            ),
        )
        # the BLS figures already out on the first run: undated, never staged
        _land(
            con,
            "bls0",
            _release(
                "bls", "BLS", "Consumer Price Index, Jul 2026: CPI +0.2%", None, baseline=True
            ),
        )
        # a Sunday release: in the week, not in Wednesday's digest
        _land(
            con,
            "kr",
            _release(
                "ftc",
                "FTC",
                "FTC Sues to Block Kroger's Acquisition of Albertsons",
                "20260823T150000",
                ["KR"],
            ),
        )
        # market context: the news feed's general headlines
        _land(
            con,
            "c1",
            _finnhub("Stocks rally as Fed signals patience on rates", "20260825T200000", []),
        )
        _land(
            con,
            "c2",
            _finnhub(
                "Stocks rally after Fed signals patience on rates", "20260825T201000", [], "CNBC"
            ),
        )
        _land(
            con,
            "c3",
            _finnhub(
                "Vanguard Group Inc. Takes Position in Apple Inc. $AAPL",
                "20260825T150000",
                ["AAPL"],
            ),
        )
        _land(con, "c4", _finnhub("Is Nvidia Stock a Buy Now?", "20260825T170000", ["NVDA"]))
        # neither stories nor context: a per-ticker pull, and Alpha Vantage
        _land(
            con,
            "co",
            _finnhub(
                "Intuit stock slides after results", "20260825T203000", ["INTU"], category="company"
            ),
        )
        _land(
            con,
            "av",
            {
                "title": "Cisco taps Supermicro for AI racks",
                "time_published": "20260825T160000",
                "source": "Benzinga",
                "url": "https://news/cisco",
                "summary": "",
                "ticker_sentiment": [
                    {"ticker": "NVDA", "relevance_score": "0.6"},
                    {"ticker": "CSCO", "relevance_score": "0.9"},
                    {"ticker": "FOREX:USD", "relevance_score": "0.9"},
                    {"ticker": "AMD", "relevance_score": "0.1"},
                ],
            },
        )
        con.execute(
            "INSERT INTO staging.stg_prices_daily VALUES"
            " ('INTU', '2026-08-25', 1, 1, 1, 1, 1, -0.034),"
            " ('INTU', '2026-08-26', 1, 1, 1, 1, 1, 0.5),"  # the digest day itself: not counted
            " ('AAPL', '2026-08-25', 1, 1, 1, 1, 1, 0.01)"
        )
        con.execute(
            "INSERT INTO staging.stg_fred_market VALUES"
            " ('SP500', '2026-08-21', 5940), ('SP500', '2026-08-24', 6000),"
            " ('SP500', '2026-08-25', 6060), ('VIXCLS', '2026-08-24', 16.0),"
            " ('VIXCLS', '2026-08-25', 15.2)"
        )
        for ticker, cap in (("INTU", 180_000), ("AAPL", 3_000_000)):  # $ millions
            con.execute(
                "INSERT INTO raw.raw_company_profile VALUES (?, ?, ?)",
                [ticker, json.dumps({"marketCapitalization": cap}), T0],
            )
        con.execute("DELETE FROM mart.model_rankings")  # init_schema seeds the repo's snapshot
        con.execute("INSERT INTO mart.model_rankings VALUES ('2026-06-30', 1, 'INTU', 'Tech', 1.0)")
    return wh


INTU_SIZE = math.log10(180e9 / 1e10) / 2
INTU_SCORE = 0.40 * 0.7 + 0.25 * 0.34 + 0.20 * INTU_SIZE + 0.15
FOMC_SCORE = 0.40 + 0.25 * 0.5 + 0.20
AAPL_SCORE = 0.40 * 0.1 + 0.25 * 0.1 + 0.20


def test_staging_types_every_source_into_one_layout(warehouse):
    assert rebuild_news_articles(warehouse) == 12  # all but the undated BLS baseline
    with warehouse.connect(read_only=True) as con:
        rows = dict(
            con.execute(
                "SELECT article_id, struct_pack(provider, feed, items, tickers, summary, published_at)"
                " FROM staging.stg_news_articles"
            ).fetchall()
        )
    assert "bls0" not in rows
    assert rows["intu"]["provider"] == "sec_edgar" and rows["intu"]["feed"] == "sec_8k"
    assert rows["intu"]["items"] == ["2.02", "9.01"] and rows["intu"]["tickers"] == ["INTU"]
    assert rows["intu"]["published_at"] == datetime(2026, 8, 25, 20, 15)
    assert (rows["fomc"]["provider"], rows["fomc"]["feed"], rows["fomc"]["items"]) == (
        "agencies",
        "fed",
        None,
    )
    assert rows["fomc"]["summary"] is None
    assert (rows["c1"]["provider"], rows["c1"]["feed"]) == ("finnhub", "finnhub_general")
    assert rows["co"]["feed"] == "finnhub_company"
    assert (rows["av"]["provider"], rows["av"]["feed"]) == ("alpha_vantage", "alpha_vantage")
    assert rows["av"]["tickers"] == ["CSCO", "NVDA"] and rows["av"]["summary"] is None


T1, T2 = "2026-08-26 12:00:00+00", "2026-08-26 13:00:00+00"


def test_staging_is_incremental_on_fetched_at(warehouse):
    rebuild_news_articles(warehouse)
    assert (
        rebuild_news_articles(warehouse) == 12
    )  # >= watermark: the last batch is re-read, idempotently
    with warehouse.connect() as con:
        _land(con, "late", _finnhub("Later story", "20260826T100000", ["MSFT"]), T1)
    assert rebuild_news_articles(warehouse) == 13  # the batch at the watermark, plus the new row
    with warehouse.connect() as con:
        _land(con, "later", _finnhub("Even later story", "20260826T110000", ["MSFT"]), T2)
    assert rebuild_news_articles(warehouse) == 2
    with warehouse.connect(read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM staging.stg_news_articles").fetchone()[0] == 14


def test_rows_staged_before_feed_existed_are_restaged_in_full(warehouse):
    with warehouse.connect() as con:
        _land(con, "late", _finnhub("Later story", "20260826T100000", ["MSFT"]), T1)
    rebuild_news_articles(warehouse)
    with warehouse.connect() as con:
        con.execute("UPDATE staging.stg_news_articles SET feed = NULL, items = NULL")
        _land(con, "later", _finnhub("Even later story", "20260826T110000", ["MSFT"]), T2)
    assert rebuild_news_articles(warehouse) == 14  # not just the 2 from the watermark on
    with warehouse.connect(read_only=True) as con:
        assert (
            con.execute(
                "SELECT COUNT(*) FROM staging.stg_news_articles WHERE feed IS NULL"
            ).fetchone()[0]
            == 0
        )
        assert con.execute(
            "SELECT items FROM staging.stg_news_articles WHERE article_id = 'intu'"
        ).fetchone()[0] == ["2.02", "9.01"]
    assert rebuild_news_articles(warehouse) == 1  # incremental again


def test_build_picks_from_primary_sources_and_keeps_the_feed_as_context(warehouse):
    rebuild_news_articles(warehouse)
    for _ in range(2):  # rebuilds in place
        out = build_daily_digest(warehouse, date(2026, 8, 26))
    assert out == {
        "period": "daily",
        "digest_date": "2026-08-26",
        "articles": 5,
        "routine_dropped": 1,
        "commentary_dropped": 1,
        "stories": 5,
        "outlets": 3,
        "picked": 3,
        "context": 1,
        "sp500_return": pytest.approx(0.01),
        "vix": 15.2,
    }
    with warehouse.connect(read_only=True) as con:
        head = con.execute(
            "SELECT COUNT(*), any_value(sp500_return), any_value(vix),"
            " any_value(session_gap_minutes) FROM mart.news_digests"
        ).fetchone()
        stories = con.execute(
            "SELECT rank, headline, move_ticker, move_return, event, reaction, size, on_site, score,"
            " coverage, category, categories FROM mart.news_digest_stories ORDER BY rank"
        ).fetchall()
        members = con.execute(
            "SELECT rank, article_id FROM mart.news_digest_articles ORDER BY 1, 2"
        ).fetchall()
        context = con.execute(
            "SELECT rank, headline, n_articles, n_outlets, score FROM mart.news_digest_context"
        ).fetchall()
    assert head == (1, pytest.approx(0.01), 15.2, None)
    # the FOMC statement on the market's +1% (half marks), then Intuit's
    # results on its -3.4%, then a director leaving Apple; the minor Fed and
    # SEC releases score under the floor
    assert [s[1] for s in stories] == [
        "Federal Reserve issues FOMC statement",
        "Intuit Reports Fourth-Quarter Fiscal 2026 Results",
        "Apple Inc.: director or officer change",
    ]
    fomc, intu, aapl = stories
    assert fomc[2:9] == (
        MARKET,
        pytest.approx(0.01),
        1.0,
        pytest.approx(0.5),
        1.0,
        0.0,
        pytest.approx(FOMC_SCORE),
    )
    assert fomc[11] == ["macro"]
    assert intu[2:9] == (
        "INTU",
        pytest.approx(-0.034),
        0.7,
        pytest.approx(0.34),
        pytest.approx(INTU_SIZE),
        1.0,
        pytest.approx(INTU_SCORE),
    )
    assert intu[9:12] == (0.0, 0.0, ["earnings"])
    assert aapl[8] == pytest.approx(AAPL_SCORE)
    assert members == [(1, "fomc"), (2, "intu"), (3, "aapl")]
    assert context == [
        (1, "Stocks rally as Fed signals patience on rates", 2, 2, pytest.approx(1 / 3))
    ]


def test_build_refuses_weekends(warehouse):
    with pytest.raises(ValueError):
        build_daily_digest(warehouse, date(2026, 8, 29))


def test_weekly_build_covers_the_week_and_compounds_the_moves(warehouse):
    rebuild_news_articles(warehouse)
    build_daily_digest(warehouse, date(2026, 8, 26))
    out = build_weekly_digest(warehouse, date(2026, 8, 28))
    assert out["period"] == "weekly" and out["articles"] == 6  # the Sunday release is in this week
    # the S&P 500 from Friday's close before the week to its last close in it
    assert out["sp500_return"] == pytest.approx(6060 / 5940 - 1) and out["vix"] == 15.2
    with warehouse.connect(read_only=True) as con:
        periods = con.execute(
            "SELECT period, COUNT(*) FROM mart.news_digests GROUP BY 1 ORDER BY 1"
        ).fetchall()
        rows = con.execute(
            "SELECT headline, move_ticker, move_return, reaction FROM mart.news_digest_stories"
            " WHERE period = 'weekly' ORDER BY rank"
        ).fetchall()
    assert periods == [("daily", 1), ("weekly", 1)]
    by_headline = {r[0]: r[1:] for r in rows}
    # Tuesday -3.4% then Wednesday +50%, compounded; full marks past 20%
    assert by_headline["Intuit Reports Fourth-Quarter Fiscal 2026 Results"] == (
        "INTU",
        pytest.approx(0.966 * 1.5 - 1),
        1.0,
    )
    assert by_headline["Federal Reserve issues FOMC statement"] == (
        MARKET,
        pytest.approx(6060 / 5940 - 1),
        pytest.approx((6060 / 5940 - 1) / 0.04),
    )
    assert "FTC Sues to Block Kroger's Acquisition of Albertsons" in by_headline
    assert rows[0][0] == "Intuit Reports Fourth-Quarter Fiscal 2026 Results"


def test_weekly_build_refuses_other_days(warehouse):
    with pytest.raises(ValueError):
        build_weekly_digest(warehouse, date(2026, 8, 29))


def test_read_api(warehouse, monkeypatch):
    from fastapi.testclient import TestClient

    from stockidence.api.app import app

    rebuild_news_articles(warehouse)
    build_daily_digest(warehouse, date(2026, 8, 25))
    build_daily_digest(warehouse, date(2026, 8, 26))
    monkeypatch.setenv("STOCKIDENCE_DB", str(warehouse.path))
    client = TestClient(app)

    latest = client.get("/api/digest/daily").json()
    assert latest["digest_date"] == "2026-08-26"
    assert latest["previous_date"] == "2026-08-25" and latest["next_date"] is None
    assert latest["window_end"] == "2026-08-26T11:00:00Z"
    assert latest["sp500_return"] == pytest.approx(0.01) and latest["vix"] == 15.2
    fomc, intu = latest["items"][:2]
    assert fomc["move_ticker"] == "S&P 500"
    assert fomc["components"] == {"event": 1.0, "reaction": 0.5, "size": 1.0, "on_site": 0.0}
    assert intu["components"] == {
        "event": 0.7,
        "reaction": 0.34,
        "size": round(INTU_SIZE, 4),
        "on_site": 1.0,
    }
    assert intu["also_covered"] == []
    assert latest["weights"] == {"event": 0.40, "reaction": 0.25, "size": 0.20, "on_site": 0.15}
    assert latest["full_marks"] == {
        "move": 0.1,
        "market_move": 0.02,
        "size_from": 1e10,
        "size_full_at": 1e12,
    }

    assert (
        client.get("/api/digest/daily", params={"date": "2026-08-25"}).json()["next_date"]
        == "2026-08-26"
    )
    assert client.get("/api/digest/daily", params={"date": "2026-08-29"}).status_code == 404
    assert client.get("/api/digest/daily", params={"date": "2026-02-30"}).status_code == 422

    build_weekly_digest(warehouse, date(2026, 8, 28))
    weekly = client.get("/api/digest/weekly").json()
    assert weekly["period"] == "weekly" and weekly["digest_date"] == "2026-08-28"
    assert weekly["full_marks"] == {
        "move": 0.2,
        "market_move": 0.04,
        "size_from": 1e10,
        "size_full_at": 1e12,
    }
    assert client.get("/api/digest/weekly", params={"date": "2026-08-21"}).status_code == 404
    assert client.get("/api/digest/monthly").status_code == 422


def test_read_api_shows_a_digest_from_the_news_feed_as_it_was_scored(warehouse, monkeypatch):
    from fastapi.testclient import TestClient

    from stockidence.api.app import app

    with warehouse.connect() as con:
        con.execute(
            """
            INSERT INTO mart.news_digests (period, digest_date, window_start, window_end, articles,
                routine_dropped, commentary_dropped, stories, outlets, session_gap_minutes, built_at)
            VALUES ('daily', '2026-07-01', '2026-06-30 11:00', '2026-07-01 11:00', 40, 10, 2, 20, 9, 0, now())
            """
        )
        con.execute(
            """
            INSERT INTO mart.news_digest_stories (period, digest_date, rank, headline, url, published_at,
                n_articles, n_outlets, coverage, reaction, category, on_site, score)
            VALUES ('daily', '2026-07-01', 1, 'Fed holds rates steady', 'https://news/fed',
                    '2026-06-30 18:00', 6, 4, 0.6667, 0.2, 1.0, 0.0, 0.50)
            """
        )
    monkeypatch.setenv("STOCKIDENCE_DB", str(warehouse.path))
    body = TestClient(app).get("/api/digest/daily", params={"date": "2026-07-01"}).json()
    assert body["items"][0]["components"] == {
        "coverage": 0.6667,
        "reaction": 0.2,
        "category": 1.0,
        "on_site": 0.0,
    }
    assert body["sp500_return"] is None and body["vix"] is None


def test_read_api_is_empty_before_the_first_digest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from stockidence.api.app import app

    Warehouse(tmp_path / "empty.duckdb").init_schema()
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "empty.duckdb"))
    body = TestClient(app).get("/api/digest/daily").json()
    assert body["digest_date"] is None and body["items"] == []
    assert body["sp500_return"] is None and body["vix"] is None


def test_init_schema_adds_the_new_columns_to_old_tables(tmp_path):
    import duckdb

    path = tmp_path / "old.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA staging")
    con.execute(
        "CREATE TABLE staging.stg_news_articles (article_id VARCHAR, published_at TIMESTAMP,"
        " provider VARCHAR, source VARCHAR, headline VARCHAR, summary VARCHAR, url VARCHAR,"
        " tickers VARCHAR[], fetched_at TIMESTAMPTZ)"
    )
    con.execute("INSERT INTO staging.stg_news_articles (article_id) VALUES ('old')")
    con.close()
    wh = Warehouse(path)
    wh.init_schema()
    wh.init_schema()  # idempotent
    with wh.connect(read_only=True) as con:
        cols = [r[0] for r in con.execute("DESCRIBE staging.stg_news_articles").fetchall()]
        old = con.execute("SELECT feed, items FROM staging.stg_news_articles").fetchall()
        story_cols = [r[0] for r in con.execute("DESCRIBE mart.news_digest_stories").fetchall()]
    assert cols[-2:] == ["feed", "items"] and old == [(None, None)]
    assert story_cols[-2:] == ["event", "size"]
