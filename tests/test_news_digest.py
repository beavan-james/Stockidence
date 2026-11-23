"""News digests: daily and weekly windows, filters, grouping, scoring,
staging, the mart build and the read API, on a temporary warehouse."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from stockidence.mart.news_digest import (
    WEEKLY,
    Article,
    build_daily_digest,
    build_weekly_digest,
    categories_of,
    digest_window,
    group_stories,
    headline_words,
    latest_digest_date,
    latest_weekly_date,
    not_news,
    score_story,
    weekly_window,
)
from stockidence.staging.staging import rebuild_news_articles
from stockidence.storage import Warehouse


def _article(aid, headline, *, hours=0, source="Reuters", tickers=(), base=datetime(2026, 8, 25, 14)):
    return Article(
        article_id=aid, published_at=base + timedelta(hours=hours), source=source,
        headline=headline, summary=None, url=f"https://x/{aid}", tickers=tuple(tickers),
        words=headline_words(headline), categories=categories_of(headline),
    )


# --- window ----------------------------------------------------------------

def test_window_runs_07_to_07_new_york_in_utc():
    # Tue Aug 25 2026 (EDT, UTC-4): Mon 07:00 ET to Tue 07:00 ET
    assert digest_window(date(2026, 8, 25)) == (datetime(2026, 8, 24, 11), datetime(2026, 8, 25, 11))


def test_monday_window_covers_the_weekend():
    start, end = digest_window(date(2026, 8, 24))
    assert start == datetime(2026, 8, 21, 11) and end == datetime(2026, 8, 24, 11)


def test_window_follows_standard_time():
    # Tue Nov 17 2026 (EST, UTC-5)
    assert digest_window(date(2026, 11, 17)) == (datetime(2026, 11, 16, 12), datetime(2026, 11, 17, 12))


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 8, 25, 10, 59, tzinfo=timezone.utc), date(2026, 8, 24)),  # 06:59 ET Tue
    (datetime(2026, 8, 25, 11, 0, tzinfo=timezone.utc), date(2026, 8, 25)),   # 07:00 ET Tue
    (datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc), date(2026, 8, 28)),   # Saturday
    (datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc), date(2026, 8, 28)),   # Mon before 07:00
])
def test_latest_digest_date(now, expected):
    assert latest_digest_date(now) == expected


def test_weekly_window_runs_saturday_to_saturday_07_new_york():
    # dated Fri Aug 28 2026 (EDT): Sat Aug 22 07:00 ET to Sat Aug 29 07:00 ET
    assert weekly_window(date(2026, 8, 28)) == (datetime(2026, 8, 22, 11), datetime(2026, 8, 29, 11))


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 11, 21, 11, 59, tzinfo=timezone.utc), date(2026, 11, 13)),  # Sat 06:59 EST
    (datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc), date(2026, 11, 20)),   # Sat 07:00 EST
    (datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc), date(2026, 11, 20)),   # Sunday
    (datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc), date(2026, 11, 13)),   # Friday evening
])
def test_latest_weekly_date(now, expected):
    assert latest_weekly_date(now) == expected


# --- filters ---------------------------------------------------------------

@pytest.mark.parametrize("headline", [
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
])
def test_routine_headlines_are_dropped(headline):
    assert not_news(headline) == "routine"


@pytest.mark.parametrize("headline", [
    "Is Nvidia Stock a Buy Now?",
    "3 Growth Stocks to Buy in September",
    "Cramer says this chip stock is a winner",
])
def test_opinion_headlines_are_dropped(headline):
    assert not_news(headline) == "commentary"


@pytest.mark.parametrize("headline", [
    "Intuit stock slides after Q4 earnings beat is followed up by soft guidance",
    "Nvidia to buy Hugging Face for $13 billion in big bet on open AI models",
    "Walmart promises price cuts after $2.9B tariff refund",
    "Fed holds rates steady as inflation cools",
    "JPMorgan beats estimates as trading revenue jumps",
])
def test_news_headlines_are_kept(headline):
    assert not_news(headline) is None


# --- grouping --------------------------------------------------------------

def test_same_stock_same_category_is_one_story_whatever_the_words():
    a = _article("1", "Broadcom Q3 revenue tops estimates on AI demand", tickers=["AVGO"])
    b = _article("2", "Broadcom shares rise after strong quarterly results", hours=2, tickers=["AVGO"])
    c = _article("3", "Oracle signs cloud deal with OpenAI", hours=1, tickers=["ORCL"])
    groups = group_stories([a, b, c])
    assert sorted(sorted(x.article_id for x in g) for g in groups) == [["1", "2"], ["3"]]


def test_shared_distinctive_words_group_across_outlets():
    a = _article("1", "Nvidia to buy Hugging Face for $13 billion", tickers=["NVDA"])
    b = _article("2", "Nvidia agrees to acquire Hugging Face in $13 billion deal", hours=1,
                 source="Bloomberg", tickers=["NVDA"])
    filler = [_article(str(i), f"Unrelated company {i} opens new plant", hours=3, tickers=[f"X{i}"])
              for i in range(3, 8)]
    groups = group_stories([a, b, *filler])
    assert any({x.article_id for x in g} == {"1", "2"} for g in groups)


def test_articles_far_apart_are_not_merged():
    a = _article("1", "Broadcom Q3 revenue tops estimates", tickers=["AVGO"])
    b = _article("2", "Broadcom Q3 revenue tops estimates", hours=48, tickers=["AVGO"])
    assert len(group_stories([a, b])) == 2


# --- scoring ---------------------------------------------------------------

def test_reaction_is_the_lead_stocks_move_not_a_co_named_one():
    arts = [
        _article("1", "Walmart promises price cuts after tariff refund", tickers=["WMT", "TGT"]),
        _article("2", "Walmart to cut prices with tariff refund", hours=1, source="CNBC", tickers=["WMT", "TGT"]),
    ]
    s = score_story(arts, {"WMT": -0.001, "TGT": 0.045}, ranked=set())
    assert s.move_ticker == "WMT"
    assert s.inputs["reaction"] == pytest.approx(0.01)


def test_no_price_for_the_lead_stock_scores_no_reaction():
    arts = [_article("1", "Valley National buys Providence Bank", tickers=["VLYPN", "WMT"])]
    s = score_story(arts, {"WMT": 0.05}, ranked=set())
    assert s.move_ticker is None and s.inputs["reaction"] == 0.0


def test_coverage_is_log_scaled_by_outlet_and_capped():
    def story(n):
        return score_story(
            [_article(str(i), "Fed holds rates steady", source=f"Outlet{i}") for i in range(n)], {}, set()
        )
    assert story(1).inputs["coverage"] == 0.0
    assert story(2).inputs["coverage"] == pytest.approx(1 / 3)
    assert story(8).inputs["coverage"] == 1.0
    assert story(12).inputs["coverage"] == 1.0


def test_a_week_needs_more_outlets_for_full_coverage():
    arts = [_article(str(i), "Fed holds rates steady", source=f"Outlet{i}") for i in range(8)]
    assert score_story(arts, {}, set(), WEEKLY).inputs["coverage"] < 1.0
    arts += [_article(str(i), "Fed holds rates steady", source=f"Outlet{i}") for i in range(8, 12)]
    assert score_story(arts, {}, set(), WEEKLY).inputs["coverage"] == 1.0


def test_same_outlet_under_two_names_counts_once():
    arts = [_article("1", "Fed holds rates", source="Investing.com"),
            _article("2", "Fed holds rates steady", source="Investing.com Canada")]
    assert score_story(arts, {}, set()).n_outlets == 1


def test_score_is_the_weighted_sum():
    arts = [_article(str(i), "Intuit Q4 earnings beat, guidance soft", source=f"O{i}", tickers=["INTU"])
            for i in range(8)]
    s = score_story(arts, {"INTU": -0.10}, {"INTU"})
    assert s.inputs == {"coverage": 1.0, "reaction": 1.0, "category": 1.0, "on_site": 1.0}
    assert s.score == pytest.approx(1.0)


# --- staging, build, API on a temp warehouse -------------------------------

def _land(con, aid, payload, fetched_at):
    con.execute(
        "INSERT INTO raw.raw_news_articles VALUES (?, ?, ?)",
        [aid, json.dumps(payload), fetched_at],
    )


def _finnhub(title, ts, related, source="Reuters"):
    return {"headline": title, "title": title, "time_published": ts, "source": source,
            "summary": f"{title}.", "url": f"https://news/{abs(hash(title))}",
            "ticker_sentiment": [{"ticker": t} for t in related]}


@pytest.fixture
def warehouse(tmp_path):
    wh = Warehouse(tmp_path / "digest.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        t0 = "2026-08-25 12:00:00+00"
        _land(con, "a1", _finnhub("Intuit stock slides after Q4 earnings beat", "20260825T202500", ["INTU"]), t0)
        _land(con, "a2", _finnhub("Intuit Q4 earnings top estimates, guidance soft", "20260825T203000",
                                  ["INTU"], "CNBC"), t0)
        _land(con, "a3", _finnhub("Vanguard Takes Position in Intuit Inc. $INTU", "20260825T150000",
                                  ["INTU"]), t0)
        _land(con, "a4", _finnhub("Weekend story", "20260823T150000", ["AAPL"]), t0)  # outside window
        # Alpha Vantage: relevance-ordered, low-relevance tickers dropped
        _land(con, "a5", {"title": "Cisco taps Supermicro for AI racks", "time_published": "20260825T160000",
                          "source": "Benzinga", "url": "https://news/cisco", "summary": "",
                          "ticker_sentiment": [{"ticker": "NVDA", "relevance_score": "0.6"},
                                               {"ticker": "CSCO", "relevance_score": "0.9"},
                                               {"ticker": "FOREX:USD", "relevance_score": "0.9"},
                                               {"ticker": "AMD", "relevance_score": "0.1"}]}, t0)
        con.execute("INSERT INTO staging.stg_prices_daily VALUES"
                    " ('INTU', '2026-08-25', 1, 1, 1, 1, 1, -0.034),"
                    " ('INTU', '2026-08-26', 1, 1, 1, 1, 1, 0.5)")  # digest day itself: not counted
        con.execute("INSERT OR REPLACE INTO mart.model_rankings VALUES ('2026-06-30', 1, 'INTU', 'Tech', 1.0)")
    return wh


def test_staging_types_both_providers_and_orders_tickers(warehouse):
    assert rebuild_news_articles(warehouse) == 5
    with warehouse.connect(read_only=True) as con:
        rows = dict(con.execute(
            "SELECT article_id, struct_pack(provider, tickers, summary, published_at)"
            " FROM staging.stg_news_articles").fetchall())
    assert rows["a1"]["provider"] == "finnhub"
    assert rows["a5"]["provider"] == "alpha_vantage"
    assert rows["a5"]["tickers"] == ["CSCO", "NVDA"]
    assert rows["a5"]["summary"] is None
    assert rows["a1"]["published_at"] == datetime(2026, 8, 25, 20, 25)


def test_staging_is_incremental_on_fetched_at(warehouse):
    rebuild_news_articles(warehouse)
    assert rebuild_news_articles(warehouse) == 5  # >= watermark: the last batch is re-read, idempotently
    with warehouse.connect() as con:
        _land(con, "a6", _finnhub("Later story", "20260826T100000", ["MSFT"]), "2026-08-26 12:00:00+00")
    assert rebuild_news_articles(warehouse) == 6  # the batch at the watermark, plus the new row
    with warehouse.connect(read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM staging.stg_news_articles").fetchone()[0] == 6


def test_build_writes_all_three_tables_and_rebuilds_in_place(warehouse):
    rebuild_news_articles(warehouse)
    for _ in range(2):
        out = build_daily_digest(warehouse, date(2026, 8, 26))
    assert out["articles"] == 4 and out["routine_dropped"] == 1
    with warehouse.connect(read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM mart.news_digests").fetchone()[0] == 1
        top = con.execute(
            "SELECT rank, n_articles, n_outlets, move_ticker, move_return, on_site"
            " FROM mart.news_digest_stories ORDER BY rank").fetchall()
        members = con.execute(
            "SELECT article_id FROM mart.news_digest_articles WHERE rank = 1 ORDER BY 1").fetchall()
    assert top[0] == (1, 2, 2, "INTU", pytest.approx(-0.034), 1.0)
    assert members == [("a1",), ("a2",)]


def test_build_refuses_weekends(warehouse):
    with pytest.raises(ValueError):
        build_daily_digest(warehouse, date(2026, 8, 29))


def test_weekly_build_covers_the_week_and_compounds_the_move(warehouse):
    rebuild_news_articles(warehouse)
    build_daily_digest(warehouse, date(2026, 8, 26))
    out = build_weekly_digest(warehouse, date(2026, 8, 28))
    assert out["period"] == "weekly" and out["articles"] == 5  # the Sunday story is in this week
    with warehouse.connect(read_only=True) as con:
        periods = con.execute(
            "SELECT period, COUNT(*) FROM mart.news_digests GROUP BY 1 ORDER BY 1").fetchall()
        top = con.execute(
            "SELECT move_ticker, move_return, reaction FROM mart.news_digest_stories"
            " WHERE period = 'weekly' AND rank = 1").fetchone()
    assert periods == [("daily", 1), ("weekly", 1)]
    # Tuesday -3.4% then Wednesday +50%, compounded; full marks past 20%
    assert top == ("INTU", pytest.approx(0.966 * 1.5 - 1), 1.0)


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
    first = latest["items"][0]
    assert first["components"]["reaction"] == pytest.approx(0.34)
    assert [a["url"] for a in first["also_covered"]] and first["url"] not in {
        a["url"] for a in first["also_covered"]}
    assert set(latest["weights"]) == {"coverage", "reaction", "category", "on_site"}

    assert client.get("/api/digest/daily", params={"date": "2026-08-25"}).json()["next_date"] == "2026-08-26"
    assert client.get("/api/digest/daily", params={"date": "2026-08-29"}).status_code == 404
    assert client.get("/api/digest/daily", params={"date": "2026-02-30"}).status_code == 422

    build_weekly_digest(warehouse, date(2026, 8, 28))
    weekly = client.get("/api/digest/weekly").json()
    assert weekly["period"] == "weekly" and weekly["digest_date"] == "2026-08-28"
    assert weekly["full_marks"] == {"coverage_outlets": 12, "move": 0.2}
    assert latest["full_marks"] == {"coverage_outlets": 8, "move": 0.1}
    assert client.get("/api/digest/weekly", params={"date": "2026-08-21"}).status_code == 404
    assert client.get("/api/digest/monthly").status_code == 422


def test_read_api_is_empty_before_the_first_digest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from stockidence.api.app import app

    Warehouse(tmp_path / "empty.duckdb").init_schema()
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "empty.duckdb"))
    body = TestClient(app).get("/api/digest/daily").json()
    assert body["digest_date"] is None and body["items"] == []
