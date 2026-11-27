"""The summaries read path: GET /api/summary/{period} over mart.news_summaries,
with each part's sources resolved through the story cards, falling back to
the last written summary."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from stockidence.api.app import app
from stockidence.storage import Warehouse

WRITTEN = datetime(2026, 8, 26, 11, 52, tzinfo=UTC)

# article_id, outlet, headline, url, published_at
ARTICLES = [
    (
        "nv1",
        "Reuters",
        "Nvidia data-center revenue tops estimates",
        "https://news/nv1",
        "2026-08-25 20:25",
    ),
    ("nv2", "CNBC", "Nvidia shares slip despite beat", "https://news/nv2", "2026-08-25 20:40"),
    (
        "fed1",
        "Yahoo Finance",
        "Fed holds rates steady",
        "https://finance.yahoo/fed1",
        "2026-08-25 18:00",
    ),
    (
        "fed2",
        "CNBC",
        "Fed keeps its rate at 4.25% to 4.5%",
        "https://news/fed2",
        "2026-08-25 18:05",
    ),
    ("pfe1", "Benzinga", "Pfizer agrees to buy Metsera", "https://news/pfe1", "2026-08-25 13:00"),
]

# story_key, source_url, status: the Fed card was read from CNBC's page, since
# the lead is on a site the scraper skips; Pfizer's story has no card.
CARDS = [
    ("nv1", "https://news/nv1", "ok"),
    ("fed1", "https://news/fed2", "ok"),
]

DAILY = "Nvidia (NVDA) said data-center revenue rose. The Federal Reserve held its rate at 4.25% to 4.5%."

# period, digest_date, part, heading, body, story_keys, status
SUMMARIES = [
    ("daily", date(2026, 8, 25), 0, None, "An older paragraph.", ["nv1"], "ok"),
    ("daily", date(2026, 8, 26), 0, None, DAILY, ["nv1", "fed1", "pfe1", "gone"], "ok"),
    # the paragraph failed its checks: no article that day
    ("daily", date(2026, 8, 27), 0, None, None, ["nv1"], "sources_only"),
    ("weekly", date(2026, 8, 28), 0, None, "The week in brief.", ["fed1", "nv1", "pfe1"], "ok"),
    ("weekly", date(2026, 8, 28), 1, "Policy and the economy", None, ["fed1"], "sources_only"),
    (
        "weekly",
        date(2026, 8, 28),
        2,
        "Earnings",
        "First paragraph.\n\nSecond paragraph.",
        ["nv1", "nv2"],
        "ok",
    ),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    wh = Warehouse(tmp_path / "summaries.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        for aid, outlet, headline, url, published in ARTICLES:
            con.execute(
                """INSERT INTO staging.stg_news_articles (article_id, published_at, provider, source,
                       headline, summary, url, tickers, fetched_at)
                   VALUES (?, ?, 'finnhub', ?, ?, NULL, ?, [], ?)""",
                [aid, published, outlet, headline, url, WRITTEN],
            )
        for key, url, status in CARDS:
            con.execute(
                """INSERT INTO mart.news_story_cards VALUES
                   (?, ?, ?, ?, 'qwen3.5:4b-q4_K_M', 'v1', 1000, 200, 150.0, ?)""",
                [key, url, json.dumps({"what": "..."}), status, WRITTEN],
            )
        # Aug 24's digest came before the first summary run: a story list only
        for day, gap in (("2026-08-24", 20), ("2026-08-26", 150)):
            con.execute(
                """INSERT INTO mart.news_digests (period, digest_date, window_start, window_end, articles,
                       routine_dropped, commentary_dropped, stories, outlets, session_gap_minutes, built_at)
                   VALUES ('daily', ?, '2026-08-25 11:00', '2026-08-26 11:00', 400, 30, 20, 120, 60, ?, ?)""",
                [day, gap, WRITTEN],
            )
        for period, day, part, heading, body, keys, status in SUMMARIES:
            con.execute(
                "INSERT INTO mart.news_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'v1', ?)",
                [
                    period,
                    day,
                    part,
                    heading,
                    body,
                    keys,
                    status,
                    "qwen3.5:4b-q4_K_M" if body else None,
                    WRITTEN,
                ],
            )
    monkeypatch.setenv("STOCKIDENCE_DB", str(wh.path))
    return TestClient(app)


def test_latest_daily_paragraph_with_its_sources(client):
    body = client.get("/api/summary/daily").json()
    # Aug 27's paragraph failed its checks, so the latest article is Aug 26's
    assert body["digest_date"] == "2026-08-26"
    assert body["previous_date"] == "2026-08-25" and body["next_date"] is None
    assert body["session_gap_minutes"] == 150
    assert body["model"] == "qwen3.5:4b-q4_K_M" and body["prompt_version"] == "v1"
    [part] = body["parts"]
    assert part["part"] == 0 and part["heading"] is None
    assert part["status"] == "ok" and part["body"] == DAILY
    assert part["sources"] == [
        {
            "headline": "Nvidia data-center revenue tops estimates",
            "outlet": "Reuters",
            "url": "https://news/nv1",
        },
        # the page the card was read from, not the skipped lead
        {
            "headline": "Fed keeps its rate at 4.25% to 4.5%",
            "outlet": "CNBC",
            "url": "https://news/fed2",
        },
        # no card: the key's own article
        {
            "headline": "Pfizer agrees to buy Metsera",
            "outlet": "Benzinga",
            "url": "https://news/pfe1",
        },
        # a key with neither a card nor an article is left out
    ]


def test_weekly_article_is_the_overview_then_its_sections(client):
    body = client.get("/api/summary/weekly").json()
    assert body["digest_date"] == "2026-08-28"
    parts = body["parts"]
    assert [(p["part"], p["heading"], p["status"]) for p in parts] == [
        (0, None, "ok"),
        (1, "Policy and the economy", "sources_only"),
        (2, "Earnings", "ok"),
    ]
    assert parts[2]["body"] == "First paragraph.\n\nSecond paragraph."
    assert [s["url"] for s in parts[2]["sources"]] == ["https://news/nv1", "https://news/nv2"]


def test_a_sources_only_part_has_no_body_but_keeps_its_sources(client):
    part = client.get("/api/summary/weekly").json()["parts"][1]
    assert part["body"] is None
    assert part["sources"] == [
        {
            "headline": "Fed keeps its rate at 4.25% to 4.5%",
            "outlet": "CNBC",
            "url": "https://news/fed2",
        }
    ]


def test_a_date_picks_that_digests_summary(client):
    older = client.get("/api/summary/daily", params={"date": "2026-08-25"}).json()
    assert older["digest_date"] == "2026-08-25"
    # the first article steps back to the digest before it, shown as its list
    assert older["previous_date"] == "2026-08-24" and older["next_date"] == "2026-08-26"
    assert older["session_gap_minutes"] is None
    assert older["parts"][0]["body"] == "An older paragraph."


def test_a_date_without_an_article_falls_back_to_the_one_before(client):
    for day in ("2026-08-27", "2026-08-29"):  # sources only; a Saturday
        body = client.get("/api/summary/daily", params={"date": day}).json()
        assert body["digest_date"] == "2026-08-26"
    weekly = client.get("/api/summary/weekly", params={"date": "2026-09-04"}).json()
    assert weekly["digest_date"] == "2026-08-28"


def test_empty_for_a_date_before_the_first_article(client):
    body = client.get("/api/summary/daily", params={"date": "2026-08-24"}).json()
    assert body["digest_date"] is None and body["parts"] == []


def test_bad_requests(client):
    assert client.get("/api/summary/daily", params={"date": "2026-02-30"}).status_code == 422
    assert client.get("/api/summary/daily", params={"date": "Aug 26"}).status_code == 422
    assert client.get("/api/summary/monthly").status_code == 422


def test_empty_before_the_first_summary_run(tmp_path, monkeypatch):
    Warehouse(tmp_path / "empty.duckdb").init_schema()
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "empty.duckdb"))
    client = TestClient(app)
    for period in ("daily", "weekly"):
        assert client.get(f"/api/summary/{period}").json() == {
            "period": period,
            "digest_date": None,
            "previous_date": None,
            "next_date": None,
            "session_gap_minutes": None,
            "model": None,
            "prompt_version": None,
            "created_at": None,
            "parts": [],
        }


def test_empty_without_a_warehouse(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "absent.duckdb"))
    body = TestClient(app).get("/api/summary/daily").json()
    assert body["digest_date"] is None and body["parts"] == []
