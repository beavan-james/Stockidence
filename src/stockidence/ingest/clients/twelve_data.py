"""Twelve Data API client.

The time-series source of record for daily prices (split-adjusted OHLCV).
Weekly/monthly bars are NOT fetched — they're resampled downstream from the
daily series. Supports both full refetch without an end date and incremental
range fetch.
"""

from __future__ import annotations

from typing import Any

from .base import APIError, BaseClient, InvalidResponseError, RateLimitError, build_query


_SYMBOL_MAP: dict[str, str] = {
    "BRK-B": "BRK.B",
    "BF-B": "BF.B",
}


class TwelveDataClient(BaseClient):
    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return _SYMBOL_MAP.get(symbol, symbol)

    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0, **kwargs: Any) -> None:
        from ...config import load_settings

        settings = load_settings()
        key: str = api_key or settings.twelve_data_api_key
        if not key:
            raise ValueError("TWELVE_DATA_API_KEY is not set")
        super().__init__(
            api_key=key,
            base_url="https://api.twelvedata.com",
            timeout=timeout,
            min_interval_seconds=kwargs.pop("min_interval_seconds", settings.min_interval_seconds["twelve_data"]),
            **kwargs,
        )

    def time_series(
        self,
        symbol: str,
        interval: str = "1day",
        *,
        adjust: str = "splits",
        outputsize: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        payload = self.request(
            "GET",
            "/time_series",
            params=build_query(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "adjust": adjust,
                    "outputsize": outputsize,
                    "start_date": start_date,
                    "end_date": end_date,
                    "order": order,
                    "apikey": self.api_key,
                }
            ),
        )
        self._raise_for_api_error(payload, symbol=symbol)
        return self._as_dict(payload, context=f"/time_series:{symbol}")

    @staticmethod
    def _raise_for_api_error(payload: Any, *, symbol: str) -> None:
        if isinstance(payload, dict):
            status = payload.get("status")
            if status == "error":
                message = payload.get("message", "unknown error")
                if payload.get("code") == 429:
                    raise RateLimitError(f"/time_series:{symbol}: {message}")
                raise APIError(f"/time_series:{symbol}: {message}")

    def quote(self, symbol: str) -> dict[str, Any]:
        symbol = self._normalize_symbol(symbol)
        payload = self.request(
            "GET",
            "/quote",
            params=build_query({"symbol": symbol, "apikey": self.api_key}),
        )
        self._raise_for_api_error(payload, symbol=symbol)
        return self._as_dict(payload, context=f"/quote:{symbol}")