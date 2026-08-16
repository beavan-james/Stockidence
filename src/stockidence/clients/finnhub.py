"""Finnhub API client.

Covers the hot-path quote, on-demand per-ticker endpoints (profile, financials,
earnings, insider/analyst sentiment, peers), and weekday calendars / symbol list.
"""

from __future__ import annotations

from typing import Any

from .base import APIError, BaseClient, InvalidResponseError, build_query


class FinnhubClient(BaseClient):
    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0, **kwargs: Any) -> None:
        from ..config import load_settings

        key: str = api_key or load_settings().finnhub_api_key
        if not key:
            raise ValueError("FINNHUB_API_KEY is not set")
        super().__init__(api_key=key, base_url="https://finnhub.io/api/v1", timeout=timeout, **kwargs)

    def _default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Finnhub-Token": str(self.api_key),
        }

    def _query(self, path: str, **params: Any) -> dict[str, Any]:
        payload = self.request("GET", path, params=build_query(params))
        self._raise_for_api_error(payload, path=path)
        return self._as_dict(payload, context=path)

    @staticmethod
    def _raise_for_api_error(payload: Any, *, path: str) -> None:
        if isinstance(payload, dict) and isinstance(payload.get("error"), str):
            raise APIError(f"{path}: {payload['error']}")

    # -- hot-path quote --

    def quote(self, symbol: str) -> dict[str, Any]:
        return self._query("/quote", symbol=symbol)

    # -- on-demand per-ticker --

    def company_profile2(self, symbol: str) -> dict[str, Any]:
        return self._query("/stock/profile2", symbol=symbol)

    def basic_financials(self, symbol: str, *, metric: str = "all") -> dict[str, Any]:
        return self._query("/stock/metrics", symbol=symbol, metric=metric)

    def financials_reported(self, symbol: str, *, freq: str = "annual") -> dict[str, Any]:
        return self._query("/stock/financials-reported", symbol=symbol, freq=freq)

    def eps_surprises(self, symbol: str, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = self.request("GET", "/stock/eps-surprises", params=build_query({"symbol": symbol, "limit": limit}))
        self._raise_for_api_error(payload, path="/stock/eps-surprises")
        if not isinstance(payload, list):
            raise InvalidResponseError("/stock/eps-surprises: expected array")
        return payload

    def insider_sentiment(self, symbol: str, *, from_date: str, to_date: str) -> dict[str, Any]:
        return self._query("/stock/insider-sentiment", **{"symbol": symbol, "from": from_date, "to": to_date})

    def recommendation_trends(self, symbol: str) -> dict[str, Any]:
        return self._query("/stock/recommendation-trends", symbol=symbol)

    def peers(self, symbol: str) -> list[str]:
        payload = self.request("GET", "/stock/peers", params=build_query({"symbol": symbol}))
        self._raise_for_api_error(payload, path="/stock/peers")
        if not isinstance(payload, list):
            raise InvalidResponseError("/stock/peers: expected array")
        return [sym for sym in payload if isinstance(sym, str)]

    def company_news(self, symbol: str, *, from_date: str, to_date: str) -> list[dict[str, Any]]:
        payload = self.request(
            "GET",
            "/company-news",
            params=build_query({"symbol": symbol, "from": from_date, "to": to_date}),
        )
        self._raise_for_api_error(payload, path="/company-news")
        if not isinstance(payload, list):
            raise InvalidResponseError("/company-news: expected array")
        return payload

    # -- weekday persistent --

    def ipo_calendar(self, *, from_date: str, to_date: str) -> dict[str, Any]:
        return self._query("/calendar/ipo", **{"from": from_date, "to": to_date})

    def earnings_calendar(self, *, from_date: str, to_date: str) -> dict[str, Any]:
        return self._query("/calendar/earnings", **{"from": from_date, "to": to_date})

    # -- monthly persistent --

    def stock_symbols(self, *, exchange: str = "US") -> list[dict[str, Any]]:
        payload = self.request("GET", "/stock/symbol", params=build_query({"exchange": exchange}))
        self._raise_for_api_error(payload, path="/stock/symbol")
        if not isinstance(payload, list):
            raise InvalidResponseError("/stock/symbol: expected array")
        return payload