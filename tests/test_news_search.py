"""All-news paging: headline search, date bounds, and the default page size."""

from __future__ import annotations

import json

import pytest

from stockidence.service import market
from stockidence.storage import Warehouse

ARTICLES = [
    ("a1", "Fed holds rates steady as inflation cools", "20260820T120000"),
    ("a2", "Nvidia earnings beat; rates barely matter", "20260819T100000"),
    ("a3", "Yields slip after CPI", "20260818T090000"),
    ("a4", "Discount chain cuts prices 50% on 100_000 items", "20260817T090000"),
]


@pytest.fixture
def news_db(tmp_path, monkeypatch):
    wh = Warehouse(tmp_path / "news.duckdb")
    wh.init_schema()
    with wh.connect() as con:
        for aid, title, ts in ARTICLES:
            payload = {
                "title": title,
                "url": f"https://news/{aid}",
                "time_published": ts,
                "source": "Example",
                "ticker_sentiment": [],
            }
            con.execute(
                "INSERT INTO raw.raw_news_articles VALUES (?, ?, current_timestamp)",
                [aid, json.dumps(payload)],
            )
    monkeypatch.setenv("STOCKIDENCE_DB", str(tmp_path / "news.duckdb"))
    market._PATH = None
    yield
    market._PATH = None


def _titles(**kwargs) -> list[str]:
    return [i["title"] for i in market.get_news_page(**kwargs)["items"]]


def test_headline_search_is_case_insensitive(news_db):
    assert _titles(q="FED") == ["Fed holds rates steady as inflation cools"]


def test_every_word_must_appear_in_any_order(news_db):
    assert _titles(q="rates nvidia") == ["Nvidia earnings beat; rates barely matter"]
    assert _titles(q="rates") == [
        "Fed holds rates steady as inflation cools",
        "Nvidia earnings beat; rates barely matter",
    ]


def test_like_wildcards_match_literally(news_db):
    assert _titles(q="%") == ["Discount chain cuts prices 50% on 100_000 items"]
    assert _titles(q="_") == ["Discount chain cuts prices 50% on 100_000 items"]


def test_headline_search_combines_with_date_bounds(news_db):
    assert _titles(q="rates", date_from="20260820") == ["Fed holds rates steady as inflation cools"]


def test_blank_search_returns_everything_ten_per_page(news_db):
    page = market.get_news_page(q="   ")
    assert page["total"] == 4
    assert page["page_size"] == 10
    assert page["page_count"] == 1
