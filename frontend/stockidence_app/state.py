from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass

import reflex as rx

from .service import market, rating_service, warehouse
from .service import sub_scores as sub_score_service

LISTS_STORAGE_KEY = "stockidence.lists"

POLL_INTERVAL_SECONDS = 10
POLL_MAX_ATTEMPTS = 30


@dataclass
class SubScoreItem:
    category_label: str
    color: str
    show_header: bool
    label: str
    sources: str
    direction: str
    score: float
    score_text: str
    weight_text: str


def _score_color(score: float) -> str:
    """Score-driven diamond color: >=65 green, >=40 amber, else red."""
    if score >= 65:
        return "#30a46c"
    if score >= 40:
        return "#f59f00"
    return "#e5484d"


def _snowflake_geometry(scores: list[dict]) -> tuple[str, str, list[dict]]:
    """Diamond grid + per-axis vertices on a 340x340 canvas (center 170,170).

    Returns (track_points, points, data): `track_points` is the fixed
    full-radius boundary diamond that anchors the chart, `points` joins the
    per-score vertices (deformed by each category's score), and `data` holds
    the per-vertex geometry for the SVG spokes, dots, and labels.
    """
    center = (170, 170)
    radius, label_radius = 115, 130
    n = len(scores)
    if n < 2:
        return "", "", list(scores)
    track: list[str] = []
    points: list[str] = []
    out: list[dict] = []
    for i in range(n):
        angle = math.pi / 2 + 2 * math.pi * i / n
        track.append(f"{center[0] + math.cos(angle) * radius:.1f},{center[1] - math.sin(angle) * radius:.1f}")
    for i, item in enumerate(scores):
        angle = math.pi / 2 + 2 * math.pi * i / n
        fraction = max(0.0, min(float(item["score"]), 100.0)) / 100.0
        cx = center[0] + math.cos(angle) * radius * fraction
        cy = center[1] - math.sin(angle) * radius * fraction
        points.append(f"{cx:.1f},{cy:.1f}")
        out.append(
            {
                **item,
                "cx": round(cx, 1),
                "cy": round(cy, 1),
                "lx": round(center[0] + math.cos(angle) * label_radius, 1),
                "ly": round(center[1] - math.sin(angle) * label_radius, 1),
                "ly2": round(center[1] - math.sin(angle) * label_radius + 16, 1),
                "lx2": round(center[0] + math.cos(angle) * label_radius - 52, 1),
                "ly3": round(center[1] - math.sin(angle) * label_radius + 8, 1),
                "score_text": f"{float(item['score']):.0f}",
            }
        )
    return " ".join(track), " ".join(points), out


class RatingState(rx.State):
    ticker: str = ""
    error: str = ""
    has_result: bool = False

    result_ticker: str = ""
    result_company: str = ""
    result_as_of: str = ""
    fair_value: float = 0.0
    target_price: float = 0.0
    confidence_score: float = 0.0
    advice: str = ""
    volatility_score: float = 0.0
    category_rows: list[dict] = []
    sub_score_rows: list[SubScoreItem] = []
    snowflake_points: str = ""
    snowflake_data: list[dict] = [
        {"label": "Valuation", "score": 0},
        {"label": "Trend", "score": 0},
        {"label": "Moat", "score": 0},
        {"label": "Sentiment", "score": 0},
    ]
    buy_plan: dict = {}
    source: str = ""

    ticker_search: str = ""
    ticker_suggestions: list[dict] = []

    movers_limit: str = "5"
    news_limit: str = "5"
    news_ticker_query: str = ""
    news_page: int = 1
    calendar_limit: str = "5"

    lists_json: str = rx.LocalStorage("[]", name=LISTS_STORAGE_KEY, sync=True)
    active_list: str = ""
    renaming_list: str = ""
    show_new_list: bool = False
    list_form_error: str = ""

    sidebar_collapsed_str: str = rx.LocalStorage("0", name="stockidence.sidebar_collapsed", sync=True)

    @rx.var
    def is_buy(self) -> bool:
        return self.advice in ("STRONG_BUY", "BUY")

    @rx.var
    def list_names(self) -> list[str]:
        return [l["name"] for l in self._parse_lists()]

    @rx.var
    def active_list_tickers(self) -> list[str]:
        if not self.active_list:
            return []
        for l in self._parse_lists():
            if l["name"] == self.active_list:
                return l["tickers"]
        return []

    @rx.var
    def has_lists(self) -> bool:
        return len(self.list_names) > 0

    @rx.var
    def confidence_score_text(self) -> str:
        return f"{self.confidence_score:.0f}"

    @rx.var
    def has_sub_scores(self) -> bool:
        return len(self.sub_score_rows) > 0

    @rx.var
    def has_fair_value(self) -> bool:
        return self.fair_value > 0

    @rx.var
    def fair_value_text(self) -> str:
        return f"${self.fair_value:,.2f}"

    @rx.var
    def target_price_text(self) -> str:
        return f"${self.target_price:,.2f}"

    @rx.var
    def quote(self) -> dict:
        if not self.result_ticker:
            return {}
        quote = market.get_quote(self.result_ticker) or {}
        if quote.get("price") is not None:
            quote["price_text"] = f"${quote['price']:,.2f}"
            if quote.get("prev_close"):
                change_pct = (
                    (quote["price"] - quote["prev_close"]) / quote["prev_close"] * 100.0
                )
                quote["change_pct"] = change_pct
                quote["change_pct_text"] = f"{change_pct:+.2f}%"
                quote["change_color"] = (
                    "green" if change_pct >= 0 else "red"
                )
        return quote

    @rx.var
    def macro_metrics(self) -> list[dict]:
        return market.get_macro_metrics()

    @rx.var
    def commodities(self) -> list[dict]:
        return market.get_commodities()

    @rx.var
    def pipeline_failures(self) -> list[dict]:
        return warehouse.get_recent_failures()

    @rx.var
    def market_movers(self) -> dict:
        return market.get_market_movers()

    @rx.var
    def top_gainers(self) -> list[dict]:
        return self.market_movers.get("top_gainers", [])[: int(self.movers_limit)]

    @rx.var
    def top_losers(self) -> list[dict]:
        return self.market_movers.get("top_losers", [])[: int(self.movers_limit)]

    @rx.var
    def ipo_calendar(self) -> list[dict]:
        return market.get_ipo_calendar(int(self.calendar_limit))

    @rx.var
    def earnings_calendar(self) -> list[dict]:
        return market.get_earnings_calendar(int(self.calendar_limit))

    def _filtered_news(self) -> list[dict]:
        news = market.get_market_news()
        query = self.news_ticker_query.strip().upper()
        if query:
            news = [
                n for n in news
                if query in (n.get("sentiment_tickers") or "").upper()
            ]
        return news

    @rx.var
    def news_all(self) -> list[dict]:
        return self._filtered_news()

    @rx.var
    def news_page_count(self) -> int:
        limit = int(self.news_limit)
        return max(1, math.ceil(len(self.news_all) / limit))

    @rx.var
    def market_news(self) -> list[dict]:
        news = self.news_all
        limit = int(self.news_limit)
        start = (max(self.news_page, 1) - 1) * limit
        return news[start : start + limit]

    def _parse_lists(self) -> list[dict]:
        try:
            parsed = json.loads(self.lists_json)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []

    def _persist_lists(self, lists: list[dict]):
        self.lists_json = json.dumps(lists)

    @rx.var
    def sidebar_collapsed(self) -> bool:
        return self.sidebar_collapsed_str == "1"

    @rx.event
    def set_ticker(self, value: str):
        self.ticker = value

    @rx.event
    def toggle_sidebar(self):
        self.sidebar_collapsed_str = "0" if self.sidebar_collapsed_str == "1" else "1"

    @rx.event
    def toggle_new_list(self):
        self.show_new_list = not self.show_new_list
        self.list_form_error = ""

    @rx.event
    def create_list(self, form_data: dict):
        name = str(form_data.get("list_name", "")).strip()
        lists = self._parse_lists()
        if not name:
            self.list_form_error = "Enter a list name first."
            return
        if any(l["name"] == name for l in lists):
            self.list_form_error = f"A list named \"{name}\" already exists."
            return
        lists.append({"name": name, "tickers": []})
        self._persist_lists(lists)
        self.active_list = name
        self.show_new_list = False
        self.list_form_error = ""

    @rx.event
    def delete_list(self, name: str):
        lists = self._parse_lists()
        self._persist_lists([l for l in lists if l["name"] != name])
        if self.active_list == name:
            self.active_list = ""

    @rx.event
    def toggle_active_list(self, name: str):
        self.active_list = name if self.active_list != name else ""

    @rx.event
    def start_rename(self, name: str):
        self.renaming_list = name

    @rx.event
    def cancel_rename(self):
        self.renaming_list = ""

    @rx.event
    def submit_rename(self, form_data: dict):
        old_name = self.renaming_list
        new_name = str(form_data.get("new_name", "")).strip()
        if not old_name or not new_name or new_name == old_name:
            self.renaming_list = ""
            return
        lists = self._parse_lists()
        if any(l["name"] == new_name for l in lists):
            self.renaming_list = ""
            return
        for l in lists:
            if l["name"] == old_name:
                l["name"] = new_name
        self._persist_lists(lists)
        if self.active_list == old_name:
            self.active_list = new_name
        self.renaming_list = ""

    @rx.event
    def add_ticker_to_active(self, form_data: dict):
        raw = str(form_data.get("ticker", "")).strip()
        normalized = rating_service.normalize_ticker(raw)
        if not rating_service.TICKER_RE.match(normalized) or not self.active_list:
            return
        lists = self._parse_lists()
        for l in lists:
            if l["name"] == self.active_list and normalized not in l["tickers"]:
                l["tickers"].append(normalized)
        self._persist_lists(lists)

    @rx.event
    def remove_ticker(self, ticker: str):
        lists = self._parse_lists()
        for l in lists:
            if l["name"] == self.active_list:
                l["tickers"] = [t for t in l["tickers"] if t != ticker]
        self._persist_lists(lists)

    @rx.event
    def save_result_to_active(self):
        if not self.has_result:
            return
        if not self.active_list:
            self.show_new_list = True
            return
        lists = self._parse_lists()
        ticker = self.result_ticker
        for l in lists:
            if l["name"] == self.active_list and ticker not in l["tickers"]:
                l["tickers"].append(ticker)
        self._persist_lists(lists)

    @rx.event
    def update_ticker_search(self, raw: str):
        self.ticker_search = raw
        if len(raw.strip()) < 2:
            self.ticker_suggestions = []
            return
        self.ticker_suggestions = warehouse.search_tickers(raw)

    @rx.event
    def update_news_ticker(self, raw: str):
        self.news_ticker_query = raw
        self.news_page = 1

    @rx.event
    def news_prev_page(self):
        if self.news_page > 1:
            self.news_page -= 1

    @rx.event
    def news_next_page(self):
        if self.news_page < self.news_page_count:
            self.news_page += 1

    @rx.event
    def set_movers_limit(self, raw: str):
        self.movers_limit = raw

    @rx.event
    def set_news_limit(self, raw: str):
        self.news_limit = raw
        self.news_page = 1

    @rx.event
    def set_calendar_limit(self, raw: str):
        self.calendar_limit = raw

    @rx.event
    def select_ticker(self, ticker: str):
        self.ticker_search = ticker
        self.ticker_suggestions = []
        self._run_search(ticker)
        if self.has_result:
            return rx.redirect(f"/stocks/{self.result_ticker}")

    @rx.event
    def submit(self, form_data: dict):
        raw = form_data.get("ticker", "").strip()
        self.ticker_suggestions = []
        self._run_search(raw)
        if self.has_result:
            return rx.redirect(f"/stocks/{self.result_ticker}")

    @rx.event
    def rate_from_list(self, ticker: str):
        self.ticker = ticker
        self._run_search(ticker)
        if self.has_result:
            return rx.redirect(f"/stocks/{self.result_ticker}")

    @rx.event
    def load_profile(self):
        symbol = getattr(self, "symbol", "")
        if not symbol:
            return
        if self.has_result and self.result_ticker == symbol:
            return RatingState.poll_rating
        self.ticker = symbol
        self._run_search(symbol)
        return RatingState.poll_rating

    @rx.event(background=True)
    async def poll_rating(self):
        """Wait for the Dagster run to land a fresh mart snapshot.

        Runs while the current search shows pending/refreshing: re-reads
        m_confidence_ratings every POLL_INTERVAL_SECONDS and swaps the UI to
        the fresh rating as soon as the snapshot's as_of changes. Bails out
        after POLL_MAX_ATTEMPTS so a failing pipeline doesn't poll forever.
        """
        ticker: str = ""
        async with self:
            ticker = self.result_ticker
        for _ in range(POLL_MAX_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            rating = warehouse.load_rating_from_warehouse(ticker)
            async with self:
                if self.source not in ("pending", "refreshing"):
                    return
                if self.result_ticker != ticker:
                    return
                if rating is None:
                    continue
                result = rating.to_dict()
                if result.get("as_of") and result["as_of"] != self.result_as_of:
                    self._apply_rating(result)
                    return

    def _run_search(self, raw: str):
        if not raw:
            self.error = "Enter a ticker to rate."
            self.has_result = False
            return

        self.error = ""
        try:
            rating = rating_service.get_rating(raw)
            self._apply_rating(rating)
        except ValueError as exc:
            self.error = str(exc)
            self.has_result = False

    def _apply_rating(self, rating: dict):
        self.result_ticker = rating["ticker"]
        self.result_company = rating["company_name"]
        self.result_as_of = rating["as_of"]
        self.fair_value = float(rating.get("fair_value") or 0.0)
        self.target_price = float(rating.get("target_price") or 0.0)
        self.confidence_score = float(rating["confidence_score"])
        self.advice = rating["advice"]
        self.volatility_score = float(rating["volatility_score"])

        labels = {
            "valuation": "Valuation",
            "trend": "Trend",
            "moat": "Moat",
            "volatility": "Volatility",
            "sentiment": "Sentiment",
        }
        self.category_rows = [
            {
                "label": labels.get(item["category"], item["category"]),
                "score": round(item["score"], 1),
                "score_text": f"{item['score']:.0f} / 100",
                "weight_text": f"{item['weight']*100:.0f}% weight",
                "color": item["category"],
            }
            for item in rating["categories"]
        ]
        _, self.snowflake_points, self.snowflake_data = _snowflake_geometry(
            [
                {
                    "label": labels.get(item["category"], item["category"]),
                    "score": round(item["score"], 1),
                    "color": _score_color(item["score"]),
                }
                for item in rating["categories"]
            ]
        )
        self.buy_plan = rating.get("buy_plan") or {}
        self.source = rating["source"]
        self.sub_score_rows = self._build_sub_score_rows(
            rating.get("components") or []
        )
        self.has_result = True

    @staticmethod
    def _build_sub_score_rows(components: list[dict]) -> list[SubScoreItem]:
        category_labels = {
            "valuation": "Valuation",
            "trend": "Trend",
            "sentiment": "Sentiment",
            "moat": "Moat",
            "volatility": "Volatility (separate)",
        }
        rows: list[SubScoreItem] = []
        for category in ("valuation", "trend", "sentiment", "moat", "volatility"):
            comps = [
                c for c in components if c.get("category", "").lower() == category
            ]
            if not comps:
                continue
            comps.sort(key=lambda c: c.get("weight", 0.0), reverse=True)
            for i, c in enumerate(comps):
                rows.append(
                    SubScoreItem(
                        category_label=category_labels[category],
                        color=category,
                        show_header=i == 0,
                        label=sub_score_service.component_label(c["component"]),
                        sources=sub_score_service.component_sources(c["component"]),
                        direction=sub_score_service.component_direction(c["component"]),
                        score=round(c["score"], 1),
                        score_text=f"{round(c['score'], 1):.0f} / 100",
                        weight_text=f"{c['weight']*100:.0f}%",
                    )
                )
        return rows