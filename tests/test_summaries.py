"""News summaries: the checks, the Ollama client, story cards, the weekly
plan and the writers, then the whole chain on a temporary warehouse. The
model is a scripted fake; the client is tested against httpx.MockTransport."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from stockidence.storage import Warehouse
from stockidence.summaries import checks, model, plan
from stockidence.summaries.cards import (
    CARD_SCHEMA,
    FALLBACK,
    OK,
    Card,
    cards_needed,
    make_card,
    render_card,
)
from stockidence.summaries.market import Headline, Market, market_block, percent
from stockidence.summaries.model import (
    ESTIMATE,
    ModelUnavailable,
    Ollama,
    PromptTooLong,
    Reply,
    TokenCounter,
    qwen_counter,
)
from stockidence.summaries.plan import ALSO, DEALS, EARNINGS, POLICY, plan_week
from stockidence.summaries.prompts import PROMPT_VERSION
from stockidence.summaries.run import make_cards, write_summaries
from stockidence.summaries.store import read_inputs, save_cards, save_summaries
from stockidence.summaries.stories import StoryInput, Text, group_stories
from stockidence.summaries.writing import SOURCES_ONLY, write_daily, write_weekly

NOW = datetime(2026, 11, 20, 13, 0, tzinfo=UTC)
ARTICLE = (
    "Nvidia said on Wednesday that third-quarter revenue rose to 57.01 billion dollars, "
    "above the 54.9 billion analysts expected. Earnings per share were 1.30 dollars. "
    "The company guided fourth-quarter revenue to 65 billion dollars, plus or minus two "
    "percent. Chief executive Jensen Huang said demand for Blackwell chips was strong. "
    "Shares of AMD and TSM also rose in late trading. "
) * 3


def _story(
    rank: int = 1,
    *,
    period: str = "daily",
    day: date = date(2026, 11, 20),
    ids: tuple[str, ...] | None = None,
    tickers: tuple[str, ...] = ("NVDA",),
    categories: tuple[str, ...] = ("earnings",),
    score: float = 0.5,
    text: str | None = ARTICLE,
    published: datetime | None = None,
    headline: str = "Nvidia beats estimates",
) -> StoryInput:
    ids = ids or (f"{period}-{day}-{rank}",)
    texts = (
        (Text(f"https://news.example/{ids[0]}", text, len(text.split()), NOW - timedelta(hours=1)),)
        if text
        else ()
    )
    return StoryInput(
        period,
        day,
        rank,
        headline,
        "Example News",
        "Nvidia topped estimates.",
        f"https://news.example/{ids[0]}",
        published or datetime(2026, 11, 19, 21, 0),
        tickers,
        categories,
        score,
        ids,
        texts,
    )


def _card_json(**over) -> str:
    card = {
        "what": "Nvidia reported third-quarter revenue of 57.01 billion dollars.",
        "companies": [{"ticker": "NVDA", "name": "Nvidia"}],
        "government": [],
        "figures": [{"label": "revenue", "value": "57.01", "unit": "USD bn"}],
        "why_it_matters": "Demand for AI chips remains strong.",
    }
    return json.dumps({**card, **over})


def _card(
    key: str,
    *,
    status: str = OK,
    what: str = "Nvidia reported revenue of 57.01 billion dollars.",
    companies=None,
    government=(),
    created: datetime = NOW,
) -> Card:
    body = {
        "what": what,
        "companies": companies if companies is not None else [{"ticker": "NVDA", "name": "Nvidia"}],
        "government": list(government),
        "figures": [],
        "why_it_matters": "",
    }
    return Card(
        key,
        f"https://news.example/{key}",
        body,
        status,
        "fake" if status == OK else None,
        PROMPT_VERSION,
        100,
        50,
        2.0,
        created,
    )


class FakeModel:
    """Answers with `respond(system, user, temperature, schema)`; records calls."""

    def __init__(self, respond, *, count_tokens=ESTIMATE):
        self.respond = respond
        self.model = "fake-model"
        self.count_tokens = count_tokens
        self.calls: list[dict] = []

    def chat(self, system, user, *, max_output, temperature=None, schema=None):
        self.calls.append(
            {"system": system, "user": user, "temperature": temperature, "schema": schema}
        )
        out = self.respond(system, user, temperature, schema)
        if isinstance(out, Exception):
            raise out
        return Reply(
            out,
            input_tokens=len(user) // 4,
            output_tokens=len(out) // 4,
            seconds=1.5,
            cut_off=False,
        )


def _prose(user: str, words: int) -> str:
    """A passable summary: a sentence naming the first ticker the prompt
    gives, then filler with no numbers, tickers or advice."""
    m = re.search(r"(\w[\w ]*?) \(([A-Z]+)\)", user)
    lead = f"{m.group(1)} ({m.group(2)}) led the news." if m else "Markets were busy."
    filler = [
        "The",
        "report",
        "drew",
        "attention",
        "across",
        "the",
        "market",
        "as",
        "traders",
        "weighed",
        "what",
        "the",
        "news",
        "meant",
        "for",
        "the",
        "sector",
        "and",
        "its",
        "suppliers",
    ]
    body = lead.split()
    while len(body) < words:
        body += filler
    return " ".join(body[:words]) + "."


def _writer(system: str, user: str, temperature, schema) -> str:
    if schema is not None:
        return _card_json()
    if "one section of a weekly" in system:
        return _prose(user, 420)
    if "opening of a weekly" in system:
        return _prose(user, 150)
    return _prose(user, 170)


# --- checks -------------------------------------------------------------------


def test_numbers_must_be_in_the_input_or_round_from_it():
    given = "Revenue rose to 13.48 billion, up 12% on 1,250 stores; two new plants."
    assert checks.unsupported_numbers("revenue of 13.48 billion", given) == []
    assert checks.unsupported_numbers("about 13.5 billion, or 13 billion", given) == []
    assert checks.unsupported_numbers("1250 stores and 2 plants, up 12%", given) == []
    assert checks.unsupported_numbers("up 14% to 13.6 billion", given) == ["14", "13.6"]
    # one significant figure is too loose to count as a rounding
    assert checks.unsupported_numbers("2 billion", "2.4 billion") == ["2"]
    # labels like Q3 aren't figures
    assert checks.unsupported_numbers("its Q3 results", "third quarter") == []


def test_tickers_and_acronyms_must_be_in_the_input():
    given = "Nvidia (NVDA) and the Federal Trade Commission (FTC)"
    assert checks.unsupported_tickers("Nvidia (NVDA) and the FTC (FTC)", given) == []
    assert checks.unsupported_tickers("Nvidia (NVDA), $AMD and Intel (NASDAQ: INTC)", given) == [
        "AMD",
        "INTC",
    ]


def test_tickers_the_input_lacks_are_dropped_from_the_text():
    given = "Nvidia (NVDA) and CrowdStrike"
    text, dropped = checks.drop_unsupported_tickers(
        "Nvidia (NVDA) rose, CrowdStrike (CRWD) fell and Intel (NASDAQ: INTC) held; $AMD too.",
        given,
    )
    assert text == "Nvidia (NVDA) rose, CrowdStrike fell and Intel held; $AMD too."
    assert dropped == ["CRWD", "INTC"]
    # a $ ticker is part of its sentence, so the check still catches it
    assert checks.unsupported_tickers(text, given) == ["AMD"]


def test_names_must_be_in_the_input():
    given = (
        "Billionaire Boehly signs US-backed deal to buy Lukoil global assets. "
        "Trump and NATO chief urge Russia to avoid actions that widen Ukraine war."
    )
    text = (
        "Talks went on. Billionaire Michael Boehly agreed to buy Lukoil assets, while "
        "Trump and NATO chief Mark Rutte urged Russia to hold back."
    )
    assert checks.unsupported_names(text, given) == ["Michael", "Mark", "Rutte"]


def test_names_allow_sentence_starts_calendar_titles_and_long_forms():
    given = "Thursday: US tariffs on Brazil. South Korea's central bank raises rates. Trump speaks."
    text = (
        "Meanwhile, on Thursday, November 26, U.S. President Trump's tariffs on Brazil hit the "
        "United States, and South Korea's central bank raised rates in its Q3 review."
    )
    assert checks.unsupported_names(text, given) == []


@pytest.mark.parametrize(
    "text",
    [
        "Investors should watch the stock.",
        "Analysts raised their price target to 200.",
        "The stock remains a buy after the report.",
        "Morgan Stanley upgraded the shares to overweight.",
        "It may be time to sell before the report.",
    ],
)
def test_advice_wording_is_caught(text):
    assert checks.advice(text)


@pytest.mark.parametrize(
    "text",
    [
        "Salesforce agreed to buy Informatica for 8 billion dollars.",
        "The company will sell its cable unit.",
        "Shares fell in a broad sell-off.",
    ],
)
def test_deal_news_is_not_advice(text):
    assert checks.advice(text) == []


def test_check_prose_reports_each_problem():
    problems = checks.check_prose("Buy rating on Nvidia (NVDA) at 99 dollars.", "Nvidia 12", (5, 6))
    assert any("numbers" in p for p in problems)
    assert any("tickers" in p for p in problems)
    assert any("advice" in p for p in problems)
    assert any("words" in p for p in problems)


# --- the Ollama client --------------------------------------------------------


def _ollama(handler, **kw) -> Ollama:
    return Ollama(
        "http://ollama:11434",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=iter(range(100)).__next__,
        **kw,
    )


def test_chat_sends_the_spec_settings_and_reads_the_reply():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {"content": "{}"},
                "prompt_eval_count": 120,
                "eval_count": 30,
                "done_reason": "stop",
            },
        )

    reply = _ollama(handler).chat(
        "sys", "user", max_output=500, temperature=0.0, schema=CARD_SCHEMA
    )
    body = seen["body"]
    assert seen["url"] == "http://ollama:11434/api/chat"
    assert body["model"] == model.MODEL and body["think"] is False and body["stream"] is False
    assert body["format"] == CARD_SCHEMA
    assert body["options"] == {
        "temperature": 0.0,
        "top_p": 0.8,
        "top_k": 20,
        "presence_penalty": 1.5,
        "num_ctx": 16384,
        "num_predict": 500,
    }
    assert (reply.text, reply.input_tokens, reply.output_tokens, reply.cut_off) == (
        "{}",
        120,
        30,
        False,
    )
    assert reply.seconds == 1


def test_default_temperature_and_cut_off_reply():
    def handler(request):
        assert json.loads(request.content)["options"]["temperature"] == 0.7
        return httpx.Response(
            200, json={"message": {"content": "partial"}, "done_reason": "length"}
        )

    assert _ollama(handler).chat("s", "u", max_output=10).cut_off


@pytest.mark.parametrize(
    "response",
    [
        httpx.ConnectError("refused"),
        httpx.Response(404, json={"error": "model 'qwen3.5:4b-q4_K_M' not found"}),
        httpx.Response(500, text="out of memory"),
    ],
)
def test_server_trouble_is_model_unavailable(response):
    def handler(request):
        if isinstance(response, Exception):
            raise response
        return response

    with pytest.raises(ModelUnavailable):
        _ollama(handler).chat("s", "u", max_output=10)


def test_a_prompt_over_budget_is_refused_before_the_call():
    def handler(request):
        raise AssertionError("no call should be made")

    llm = _ollama(handler, count_tokens=TokenCounter("fixed", lambda text: 10_000))
    with pytest.raises(PromptTooLong) as e:
        llm.chat("s", "u", max_output=1000)
    assert e.value.budget == int(16384 * 0.9) - 1000


def test_qwen_counter_reads_a_tokenizer_file(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    tok = Tokenizer(WordLevel({"[UNK]": 0, "nvidia": 1, "beats": 2}, unk_token="[UNK]"))
    tok.pre_tokenizer = Whitespace()
    path = tmp_path / "tokenizer.json"
    tok.save(str(path))
    counter = qwen_counter(path)
    assert counter("nvidia beats estimates again") == 4
    assert qwen_counter(tmp_path / "missing.json") is ESTIMATE
    assert ESTIMATE("abcdefg") == 3


# --- cards --------------------------------------------------------------------


def test_a_card_that_passes_is_kept():
    llm = FakeModel(lambda *a: _card_json())
    card = make_card(llm, _story(), NOW)
    assert card.status == OK and card.model == "fake-model"
    assert card.source_url == "https://news.example/daily-2026-11-20-1"
    assert card.card["figures"][0]["value"] == "57.01"
    assert llm.calls[0]["schema"] == CARD_SCHEMA and llm.calls[0]["temperature"] is None
    assert "Story tickers: NVDA" in llm.calls[0]["user"] and "57.01 billion" in llm.calls[0]["user"]


def test_a_failed_card_is_asked_again_at_temperature_zero():
    replies = iter(
        [_card_json(figures=[{"label": "revenue", "value": "58", "unit": "USD bn"}]), _card_json()]
    )
    llm = FakeModel(lambda *a: next(replies))
    card = make_card(llm, _story(), NOW)
    assert card.status == OK
    assert [c["temperature"] for c in llm.calls] == [None, 0.0]
    assert card.problems == ("numbers not in the input: 58",)
    assert card.seconds == 3.0  # both attempts


def test_two_failures_fall_back_to_the_feed_summary():
    bad = _card_json(companies=[{"ticker": "INTC", "name": "Intel"}])
    llm = FakeModel(lambda *a: bad)
    card = make_card(llm, _story(), NOW)
    assert card.status == FALLBACK and card.model is None
    assert card.card["what"] == "Nvidia topped estimates."
    assert card.card["companies"] == [{"ticker": "NVDA", "name": ""}]
    assert card.source_url == "https://news.example/daily-2026-11-20-1"  # the lead's link
    assert len(llm.calls) == 2 and card.input_tokens > 0


def test_tickers_named_in_the_article_pass():
    llm = FakeModel(
        lambda *a: _card_json(
            companies=[{"ticker": "nvda", "name": "Nvidia"}, {"ticker": "TSM", "name": "TSMC"}]
        )
    )
    card = make_card(llm, _story(), NOW)
    assert card.status == OK and [c["ticker"] for c in card.card["companies"]] == ["NVDA", "TSM"]


def test_a_fallback_keeps_the_feed_summary_s_opening():
    from stockidence.summaries.cards import first_sentences

    long = "Revenue rose 5%. Margins held. Guidance went up. " + "More detail here. " * 40
    assert first_sentences(long) == "Revenue rose 5%. Margins held."
    one = "A " + "very " * 120 + "long opening sentence. Then another."
    assert first_sentences(one) == one.split(". ")[0] + "."  # never less than the first
    assert first_sentences("U.S. stocks rose 2.5% on Monday. Bonds fell.") == (
        "U.S. stocks rose 2.5% on Monday. Bonds fell."
    )


def test_no_article_means_a_fallback_without_a_call():
    llm = FakeModel(lambda *a: pytest.fail("no call expected"))
    card = make_card(llm, _story(text=None), NOW)
    assert card.status == FALLBACK and card.input_tokens == 0 and llm.calls == []


def test_the_server_going_away_is_not_a_fallback():
    llm = FakeModel(lambda *a: ModelUnavailable("down"))
    with pytest.raises(ModelUnavailable):
        make_card(llm, _story(), NOW)


# --- which cards to make ------------------------------------------------------


def test_stories_sharing_an_article_share_cards():
    daily = _story(1, ids=("a1", "a2"))
    other = _story(2, ids=("b1",))
    weekly = _story(1, period="weekly", ids=("w1", "a2", "a3"))
    groups = group_stories([weekly, other, daily])
    assert [[s.key for s in g] for g in groups] == [["a1", "w1"], ["b1"]]

    # the daily card covers the weekly story; only the other story needs one
    jobs = cards_needed(groups, {"a1": _card("a1")})
    assert [(key, s.key) for key, s in jobs] == [("b1", "b1")]


def test_a_fallback_card_is_read_again_once_its_article_arrives():
    old = _card("a1", status=FALLBACK, created=NOW - timedelta(days=3))
    story = _story(ids=("a1",))  # its text was extracted an hour ago
    assert [k for k, _ in cards_needed([[story]], {"a1": old})] == ["a1"]
    # not when the text was already there when the fallback was made
    assert cards_needed([[story]], {"a1": replace(old, created_at=NOW)}) == []
    assert [k for k, _ in cards_needed([[story]], {"a1": _card("a1")}, redo=True)] == ["a1"]


# --- the weekly plan ----------------------------------------------------------


def _item_story(n: int, tickers, categories, score, hours=0, headline="Story"):
    return _story(
        n,
        period="weekly",
        day=date(2026, 11, 21),
        ids=(f"w{n}",),
        tickers=tickers,
        categories=categories,
        score=score,
        headline=headline,
        published=datetime(2026, 11, 17, 9) + timedelta(hours=hours),
    )


def test_plan_orders_topics_then_sectors_and_folds_small_sections():
    stories = [
        _item_story(1, ("NVDA",), ("earnings",), 0.9),
        _item_story(2, ("WMT",), ("earnings",), 0.6),
        _item_story(3, (), ("macro",), 0.8),
        _item_story(4, ("FED",), ("policy",), 0.5),
        _item_story(5, ("XOM",), (), 0.7),
        _item_story(6, ("CVX",), (), 0.4),
        _item_story(7, ("JPM",), (), 0.95),  # alone in Financials: folds
        _item_story(8, ("ABC",), ("deal",), 0.3),  # one deal: folds
        _item_story(9, ("ZZZ",), (), 0.2),  # no sector
    ]
    cards = {
        s.key: _card(s.key, companies=[{"ticker": t, "name": t} for t in s.tickers])
        for s in stories
    }
    sectors = {"XOM": "Energy", "CVX": "Energy", "JPM": "Financials"}
    sections = plan_week(group_stories(stories), cards, sectors, ESTIMATE)
    assert [s.heading for s in sections] == [POLICY, EARNINGS, "Energy", ALSO]
    assert [s.story_keys for s in sections] == [
        ["w3", "w4"],
        ["w1", "w2"],
        ["w5", "w6"],
        ["w7", "w8", "w9"],
    ]
    assert DEALS not in [s.heading for s in sections]


def test_one_company_through_the_week_is_one_thread_in_date_order():
    stories = [
        _item_story(1, ("NVDA",), ("earnings",), 0.9, hours=48),
        _item_story(2, ("WMT",), ("earnings",), 0.95),
        _item_story(3, ("NVDA",), ("earnings",), 0.4, hours=0),
    ]
    cards = {s.key: _card(s.key) for s in stories}
    [section] = plan_week(group_stories(stories), cards, {}, ESTIMATE)
    # the NVDA thread (1.3 in all) before WMT (0.95), its items by date
    assert section.story_keys == ["w3", "w1", "w2"]


def test_a_section_over_the_token_limit_splits(monkeypatch):
    monkeypatch.setattr(plan, "SECTION_TOKENS", 40)  # two 16-word cards
    stories = [_item_story(n, (f"T{n}",), ("earnings",), 1 - n / 10) for n in range(1, 5)]
    cards = {s.key: _card(s.key) for s in stories}
    sections = plan_week(
        group_stories(stories), cards, {}, TokenCounter("words", lambda t: len(t.split()))
    )
    assert [s.heading for s in sections] == [f"{EARNINGS}, part 1", f"{EARNINGS}, part 2"]
    assert sum(len(s.story_keys) for s in sections) == 4


# --- writing ------------------------------------------------------------------


def test_daily_paragraph_from_the_cards():
    stories = [_story(1), _story(2, ids=("b",), tickers=("AMD",))]
    pairs = [
        (stories[0], _card("daily-2026-11-20-1")),
        (stories[1], _card("b", what="AMD gained.", companies=[{"ticker": "AMD", "name": "AMD"}])),
    ]
    llm = FakeModel(_writer)
    summary = write_daily(llm, date(2026, 11, 20), pairs, NOW)
    assert summary.status == OK and summary.part == 0 and summary.heading is None
    assert summary.story_keys == ("daily-2026-11-20-1", "b")
    assert 150 <= len(summary.body.split()) <= 200 and "\n" not in summary.body
    user = llm.calls[0]["user"]
    assert user.startswith("Daily market news summary for Friday 2026-11-20")
    assert "1. Nvidia beats estimates (Example News)" in user and "Companies: Nvidia (NVDA)" in user


def test_a_daily_that_fails_twice_shows_only_its_sources():
    llm = FakeModel(lambda s, u, t, sc: _prose(u, 170) + " Investors should buy Nvidia.")
    summary = write_daily(llm, date(2026, 11, 20), [(_story(), _card("daily-2026-11-20-1"))], NOW)
    assert summary.status == SOURCES_ONLY and summary.body is None and summary.model is None
    assert [c["temperature"] for c in llm.calls] == [None, 0.0]
    assert any("advice" in p for p in summary.problems)


def test_a_ticker_the_cards_lack_is_dropped_not_failed():
    llm = FakeModel(lambda s, u, t, sc: "Nvidia (NVDA) led the news. " + _prose(u, 165))
    card = _card("daily-2026-11-20-1", companies=[{"ticker": "", "name": "Nvidia"}])
    summary = write_daily(llm, date(2026, 11, 20), [(_story(tickers=()), card)], NOW)
    assert summary.status == OK and summary.body.startswith("Nvidia led the news.")
    assert summary.problems == ("dropped tickers not in the input: NVDA",)
    assert len(llm.calls) == 1


def test_the_retry_names_the_names_to_leave_out():
    # complies only once the prompt tells it which names to leave out
    llm = FakeModel(
        lambda s, u, t, sc: _prose(u, 170) + ("" if "Jensen" in u else " It cited Jensen Huang.")
    )
    summary = write_daily(llm, date(2026, 11, 20), [(_story(), _card("daily-2026-11-20-1"))], NOW)
    assert summary.status == OK and "Jensen" not in summary.body
    assert summary.problems == ("names not in the input: Jensen, Huang",)
    first, second = (c["user"] for c in llm.calls)
    assert "Jensen" not in first
    assert second.startswith(first) and second.endswith(
        "Don't use these names, which the cards don't give: Jensen, Huang. "
        "Name people and organizations only as the cards do."
    )


def test_headings_and_lists_are_rejected():
    llm = FakeModel(lambda s, u, t, sc: "## Markets\n- " + _prose(u, 170))
    summary = write_daily(llm, date(2026, 11, 20), [(_story(), _card("daily-2026-11-20-1"))], NOW)
    assert summary.status == SOURCES_ONLY and summary.problems == ("headings or lists",) * 2


def test_weekly_article_is_an_overview_then_sections():
    stories = [
        _item_story(1, ("NVDA",), ("earnings",), 0.9),
        _item_story(2, ("WMT",), ("earnings",), 0.6),
        _item_story(3, (), ("macro",), 0.8, headline="Fed holds rates"),
        _item_story(4, (), ("macro",), 0.5, headline="Jobs report"),
    ]
    cards = {s.key: _card(s.key) for s in stories}
    cards["w3"] = _card(
        "w3", what="The Fed held rates.", companies=[], government=["Federal Reserve"]
    )
    cards["w4"] = _card(
        "w4", what="Payrolls rose.", companies=[], government=["Bureau of Labor Statistics"]
    )
    sections = plan_week(group_stories(stories), cards, {}, ESTIMATE)
    llm = FakeModel(_writer)
    parts = write_weekly(llm, date(2026, 11, 21), sections, NOW)
    assert [(p.part, p.heading, p.status) for p in parts] == [
        (0, None, OK),
        (1, POLICY, OK),
        (2, EARNINGS, OK),
    ]
    assert parts[0].story_keys == ("w3", "w4", "w1", "w2")
    policy_prompt = llm.calls[0]["user"]
    assert "This section: Policy and the economy" in policy_prompt
    assert "- Earnings: Nvidia" in policy_prompt  # what the other section covers
    assert llm.calls[-1]["system"].startswith("You write the opening")


# --- the market ---------------------------------------------------------------

SLIP = Headline("m1", "Stocks slip as yields climb",
                "Wall Street fell on Thursday as Treasury yields rose. The Nasdaq led losses. "
                "Oil was flat.", "Reuters", "https://news.example/m1")
MARKET = Market(-0.0083, 15.234, (SLIP, Headline("m2", "Oil steadies", None, None, "https://news.example/m2")))


@pytest.mark.parametrize(("r", "text"), [
    (0.0083, "up 0.8%"), (-0.012, "down 1.2%"), (0.0004, "up 0.04%"), (-0.00001, "unchanged"),
])
def test_a_return_is_written_with_its_direction(r, text):
    assert percent(r) == text


def test_the_daily_market_block_names_the_session_and_trims_summaries():
    assert market_block(MARKET, "daily", date(2026, 11, 20)) == (
        "Market:\n"
        "S&P 500 in Thursday's session: down 0.8%. VIX at the close: 15.2.\n"
        "Most covered market headlines:\n"
        "- Reuters: Stocks slip as yields climb — Wall Street fell on Thursday as Treasury yields "
        "rose. The Nasdaq led losses.\n"
        "- Oil steadies")


def test_the_weekly_market_block_covers_the_week():
    block = market_block(Market(0.012, None), "weekly", date(2026, 11, 20))
    assert block == "Market:\nS&P 500 over the week: up 1.2%."
    assert "at the week's last close: 15.2" in market_block(Market(None, 15.2), "weekly", date(2026, 11, 20))


def test_no_market_no_block():
    assert market_block(None, "daily", date(2026, 11, 20)) is None
    assert market_block(Market(None, None), "daily", date(2026, 11, 20)) is None


def test_the_daily_paragraph_gets_the_market_and_keeps_its_headlines():
    # a sentence on the market from the block passes the checks
    line = " Reuters reported that stocks fell 0.8% in Thursday's session as Treasury yields rose."
    llm = FakeModel(lambda s, u, t, sc: _prose(u, 160) + line)
    summary = write_daily(llm, date(2026, 11, 20), [(_story(), _card("daily-2026-11-20-1"))], NOW, MARKET)
    assert summary.status == OK and summary.body.endswith(line.strip())
    assert summary.story_keys == ("daily-2026-11-20-1", "m1", "m2")
    user, system = llm.calls[0]["user"], llm.calls[0]["system"]
    assert user.endswith(market_block(MARKET, "daily", date(2026, 11, 20)))
    assert "When a Market block follows the cards" in system


def test_an_outlet_the_block_lacks_still_fails():
    # the name check skips a sentence's first word, so this one is mid-sentence
    line = " Stocks fell 0.8% in Thursday's session, Bloomberg reported."
    llm = FakeModel(lambda s, u, t, sc: _prose(u, 160) + line)
    summary = write_daily(llm, date(2026, 11, 20), [(_story(), _card("daily-2026-11-20-1"))], NOW, MARKET)
    assert summary.status == SOURCES_ONLY
    assert any("Bloomberg" in p for p in summary.problems)


def test_the_weekly_overview_gets_the_week_s_market_and_sections_do_not():
    stories = [_item_story(1, ("NVDA",), ("earnings",), 0.9), _item_story(2, ("WMT",), ("earnings",), 0.6)]
    cards = {s.key: _card(s.key) for s in stories}
    sections = plan_week(group_stories(stories), cards, {}, ESTIMATE)
    llm = FakeModel(_writer)
    parts = write_weekly(llm, date(2026, 11, 20), sections, NOW, MARKET)
    assert parts[0].story_keys == ("w1", "w2", "m1", "m2")
    assert all("m1" not in p.story_keys for p in parts[1:])
    *section_calls, overview = llm.calls
    assert "S&P 500 over the week: down 0.8%." in overview["user"]
    assert all("Market:" not in c["user"] for c in section_calls)


def test_render_card_shows_tickers_after_names():
    text = render_card(
        _card(
            "k",
            companies=[
                {"ticker": "NVDA", "name": "Nvidia"},
                {"ticker": "", "name": "OpenAI"},
                {"ticker": "AMD", "name": ""},
            ],
        ),
        _story(),
        dated=True,
    )
    assert "Companies: Nvidia (NVDA), OpenAI, AMD" in text
    assert text.startswith("Thu 2026-11-19: Nvidia beats estimates (Example News)")


# --- the whole chain on a warehouse ------------------------------------------


@pytest.fixture
def wh(tmp_path):
    w = Warehouse(tmp_path / "summaries.duckdb")
    w.init_schema()
    return w


def _seed(
    wh: Warehouse,
    period: str,
    day: str,
    rank: int,
    ids: list[str],
    *,
    text: bool = True,
    tickers=("NVDA",),
    categories=("earnings",),
) -> None:
    with wh.connect() as con:
        con.execute(
            "INSERT INTO mart.news_digest_stories (period, digest_date, rank, headline, summary, url,"
            " source, published_at, tickers, categories, n_articles, n_outlets, coverage, reaction,"
            " category, on_site, score) VALUES (?, ?, ?, 'Nvidia beats estimates', 'Nvidia topped"
            " estimates.', ?, 'Example News', '2026-11-19 21:00', ?, ?, 1, 1, 0, 0, 0, 0, 0.5)",
            [period, day, rank, f"https://news.example/{ids[0]}", list(tickers), list(categories)],
        )
        for aid in ids:
            con.execute(
                "INSERT INTO mart.news_digest_articles VALUES (?, ?, ?, ?)",
                [period, day, rank, aid],
            )
            con.execute(
                "INSERT OR REPLACE INTO staging.stg_news_articles (article_id, published_at, headline, url)"
                " VALUES (?, '2026-11-19 21:00', 'x', ?)",
                [aid, f"https://news.example/{aid}"],
            )
        if text:
            con.execute(
                "INSERT OR REPLACE INTO staging.stg_news_article_text VALUES (?, ?, ?, false, 'x', ?)",
                [
                    f"https://news.example/{ids[0]}",
                    ARTICLE,
                    len(ARTICLE.split()),
                    NOW - timedelta(hours=1),
                ],
            )


def _run(wh, llm, read, write, redo=False):
    clock = iter(NOW + timedelta(minutes=k) for k in range(1000)).__next__
    inputs = read_inputs(wh, read, write)
    card_run = make_cards(llm, inputs, clock, redo=redo)
    save_cards(wh, list(card_run.made))
    cards = {**inputs.cards, **{c.story_key: c for c in card_run.made}}
    summary_run = write_summaries(llm, inputs, cards, clock, redo=redo)
    save_summaries(wh, list(summary_run.written))
    return card_run, summary_run


def _rows(wh, sql):
    with wh.connect(read_only=True) as con:
        return con.execute(sql).fetchall()


def test_daily_chain_writes_cards_and_the_paragraph_once(wh):
    day = date(2026, 11, 20)
    _seed(wh, "daily", "2026-11-20", 1, ["a1", "a2"])
    _seed(wh, "daily", "2026-11-20", 2, ["b1"], text=False, tickers=("AMD",))
    llm = FakeModel(_writer)
    cards, summaries = _run(wh, llm, [("daily", day)], [("daily", day)])
    assert cards.error is None and summaries.error is None
    assert _rows(
        wh, "SELECT story_key, status, source_url, model FROM mart.news_story_cards ORDER BY 1"
    ) == [
        ("a1", "ok", "https://news.example/a1", "fake-model"),
        ("b1", "fallback", "https://news.example/b1", None),
    ]
    [(part, _body, keys, status, version)] = _rows(
        wh, "SELECT part, body, story_keys, status, prompt_version FROM mart.news_summaries"
    )
    assert (part, keys, status, version) == (0, ["a1", "b1"], "ok", PROMPT_VERSION)
    assert len(llm.calls) == 2  # one card (b1 has no article) and the paragraph

    # a second run makes nothing new
    again = FakeModel(_writer)
    cards, summaries = _run(wh, again, [("daily", day)], [("daily", day)])
    assert cards.made == () and summaries.skipped == (("daily", day),) and again.calls == []


def test_weekly_chain_reuses_the_week_s_daily_cards(wh):
    friday = date(2026, 11, 21) - timedelta(days=1)
    _seed(wh, "daily", "2026-11-18", 1, ["a1"])
    _seed(wh, "daily", "2026-11-19", 1, ["c1"], tickers=("WMT",))
    _run(wh, FakeModel(_writer), [("daily", date(2026, 11, 18)), ("daily", date(2026, 11, 19))], [])
    assert len(_rows(wh, "SELECT * FROM mart.news_story_cards")) == 2

    # the week's digest: one story joins Tuesday's, one is new
    _seed(wh, "weekly", "2026-11-20", 1, ["w1", "a1"])
    _seed(wh, "weekly", "2026-11-20", 2, ["w2"], tickers=("TSM",))
    read = [("weekly", friday), *[("daily", friday - timedelta(days=k)) for k in range(4, -1, -1)]]
    llm = FakeModel(_writer)
    cards, _ = _run(wh, llm, read, [("weekly", friday)])
    assert [c.story_key for c in cards.made] == ["w2"]
    parts = _rows(
        wh, "SELECT part, heading, status, story_keys FROM mart.news_summaries ORDER BY part"
    )
    assert [(p, h, s) for p, h, s, _ in parts] == [(0, None, "ok"), (1, EARNINGS, "ok")]
    assert sorted(parts[0][3]) == ["a1", "c1", "w2"]


def test_the_server_going_away_keeps_the_finished_cards(wh):
    day = date(2026, 11, 20)
    for rank in (1, 2, 3):
        _seed(wh, "daily", "2026-11-20", rank, [f"s{rank}"])
    answers = iter([_card_json(), ModelUnavailable("connection refused")])
    llm = FakeModel(lambda *a: next(answers))
    inputs = read_inputs(wh, [("daily", day)], [("daily", day)])
    run = make_cards(llm, inputs, lambda: NOW)
    assert [c.story_key for c in run.made] == ["s1"] and "refused" in run.error


def test_a_rebuilt_digest_is_written_again(wh):
    day = date(2026, 11, 20)
    _seed(wh, "daily", "2026-11-20", 1, ["a1"])
    _run(wh, FakeModel(_writer), [("daily", day)], [("daily", day)])
    _seed(wh, "daily", "2026-11-20", 2, ["b1"])  # the digest now has another story
    llm = FakeModel(_writer)
    _, summaries = _run(wh, llm, [("daily", day)], [("daily", day)])
    assert [s.story_keys for s in summaries.written] == [("a1", "b1")]


def _seed_market(wh: Warehouse, period: str, day: str, sp500: float | None, vix: float | None,
                 headlines: list[tuple[str, str]]) -> None:
    """The digest's row with its market figures, and its context headlines
    (article id, headline) with their articles."""
    with wh.connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO mart.news_digests (period, digest_date, window_start, window_end,"
            " articles, routine_dropped, commentary_dropped, stories, outlets, built_at, sp500_return,"
            " vix) VALUES (?, ?, '2026-11-19 12:00', '2026-11-20 12:00', 3, 0, 0, 3, 1, ?, ?, ?)",
            [period, day, NOW, sp500, vix])
        con.execute("DELETE FROM mart.news_digest_context WHERE period = ? AND digest_date = ?", [period, day])
        for rank, (aid, headline) in enumerate(headlines, start=1):
            url = f"https://feed.example/{aid}"
            con.execute(
                "INSERT INTO mart.news_digest_context VALUES (?, ?, ?, ?, NULL, ?, 'Reuters',"
                " '2026-11-19 20:00', 2, 2, 0.5)", [period, day, rank, headline, url])
            con.execute(
                "INSERT OR REPLACE INTO staging.stg_news_articles (article_id, published_at, headline, url)"
                " VALUES (?, '2026-11-19 20:00', ?, ?)", [aid, headline, url])


def test_the_chain_gives_the_paragraph_its_market_and_rewrites_when_it_changes(wh):
    day = date(2026, 11, 20)
    _seed(wh, "daily", "2026-11-20", 1, ["a1"])
    _seed_market(wh, "daily", "2026-11-20", -0.0083, 15.2, [("m1", "Stocks slip as yields climb")])
    llm = FakeModel(_writer)
    _run(wh, llm, [("daily", day)], [("daily", day)])
    assert "- Reuters: Stocks slip as yields climb" in llm.calls[-1]["user"]
    assert _rows(wh, "SELECT story_keys FROM mart.news_summaries") == [(["a1", "m1"],)]

    again = FakeModel(_writer)
    _, summaries = _run(wh, again, [("daily", day)], [("daily", day)])
    assert summaries.skipped == (("daily", day),) and again.calls == []

    # the digest is rebuilt with other headlines: the paragraph is written again
    _seed_market(wh, "daily", "2026-11-20", -0.0083, 15.2, [("m2", "Oil steadies")])
    _, summaries = _run(wh, FakeModel(_writer), [("daily", day)], [("daily", day)])
    assert [s.story_keys for s in summaries.written] == [("a1", "m2")]


def test_a_digest_from_before_the_market_context_has_no_block(wh):
    day = date(2026, 11, 20)
    _seed(wh, "daily", "2026-11-20", 1, ["a1"])
    _seed_market(wh, "daily", "2026-11-20", None, None, [])
    llm = FakeModel(_writer)
    _run(wh, llm, [("daily", day)], [("daily", day)])
    assert "Market:" not in llm.calls[-1]["user"]
    assert _rows(wh, "SELECT story_keys FROM mart.news_summaries") == [(["a1"],)]
