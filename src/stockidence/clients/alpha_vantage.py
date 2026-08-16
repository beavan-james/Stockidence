"""Alpha Vantage API client.

Used for persistent market-wide data (monthly: gold/silver + macro indices),
weekday movers, daily market news, and the on-demand earnings call transcript.
Does NOT cover prices/technicals — those moved to Twelve Data and derivation.
"""

from __future__ import annotations

from typing import Any

from .base import APIError, BaseClient, InvalidResponseError, RateLimitError, build_query


class AlphaVantageClient(BaseClient):
    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0, **kwargs: Any) -> None:
        from ..config import load_settings

        key: str = api_key or load_settings().alpha_vantage_api_key
        if not key:
            raise ValueError("ALPHA_VANTAGE_API_KEY is not set")
        super().__init__(api_key=key, base_url="https://www.alphavantage.co", timeout=timeout, **kwargs)

    def _query(self, function: str, **params: Any) -> dict[str, Any]:
        payload = self.request(
            "GET",
            "/query",
            params=build_query({"function": function, "apikey": self.api_key, **params}),
        )
        self._raise_for_api_error(payload, function=function)
        return self._as_dict(payload, context=function)

    @staticmethod
    def _raise_for_api_error(payload: Any, *, function: str) -> None:
        if isinstance(payload, dict):
            if payload.get("Information"):
                raise RateLimitError(f"{function}: {payload['Information']}")
            if payload.get("Note"):
                raise RateLimitError(f"{function}: {payload['Note']}")
            if payload.get("Error Message") or payload.get("error"):
                msg = payload.get("Error Message") or payload.get("error")
                raise APIError(f"{function}: {msg}")

    # -- monthly persistent --

    def gold(self) -> dict[str, Any]:
        return self._query("GOLD")

    def silver(self) -> dict[str, Any]:
        return self._query("SILVER")

    def inflation(self) -> dict[str, Any]:
        return self._query("INFLATION")

    def cpi(self) -> dict[str, Any]:
        return self._query("CPI")

    def unemployment(self) -> dict[str, Any]:
        return self._query("UNEMPLOYMENT")

    def federal_funds_rate(self, interval: str = "monthly") -> dict[str, Any]:
        return self._query("FEDERAL_FUNDS_RATE", interval=interval)

    def natural_gas(self) -> dict[str, Any]:
        return self._query("NATURAL_GAS")

    def real_gdp_per_capita(self) -> dict[str, Any]:
        return self._query("REAL_GDP_PER_CAPITA")

    # -- weekday persistent --

    def top_gainers_losers(self) -> dict[str, Any]:
        return self._query("TOP_GAINERS_LOSERS")

    # -- daily persistent --

    def market_news(self, *, tickers: str | None = None, time_from: str | None = None,
                    time_to: str | None = None, limit: int | None = 100,
                    sort: str = "LATEST") -> dict[str, Any]:
        return self._query(
            "NEWS_SENTIMENT",
            tickers=tickers,
            time_from=time_from,
            time_to=time_to,
            limit=limit,
            sort=sort,
        )

    # -- on-demand --

    def earnings_call_transcript(self, symbol: str, quarter: str) -> dict[str, Any]:
        return self._query("EARNINGS_CALL_TRANSCRIPT", symbol=symbol, quarter=quarter)