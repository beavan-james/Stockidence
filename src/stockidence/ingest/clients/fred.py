"""FRED (Federal Reserve Bank of St. Louis) API client.

Covers the market-wide index series the model reads as PIT regime features:
VIX (`VIXCLS`) and the S&P 500 price index (`SP500`). Stays on FRED's free
tier — a free API key, effectively no daily-observation limits for two daily
series, and (unlike most providers) never-revised market series.

    https://fred.stlouisfed.org/docs/api/fred/series_observations.html

Two data caveats that shape how the series are used downstream:
  - `SP500` is a PRICE index (no dividends), and S&P's licensing agreement
    with FRED limits daily history to ~10 years — earlier history comes from
    another source if the backtest window needs it.
  - Market series publish after the session close, so a next-day fetch is
    point-in-time correct; the observation date, not the fetch date, is
    stored as the `date` key.
"""

from __future__ import annotations

from typing import Any

from .base import APIError, BaseClient, InvalidResponseError, build_query


class FredClient(BaseClient):
    def __init__(self, *, api_key: str | None = None, timeout: float = 30.0, **kwargs: Any) -> None:
        from ...config import load_settings

        settings = load_settings()
        key: str = api_key or settings.fred_api_key
        if not key:
            raise ValueError("FRED_API_KEY is not set")
        super().__init__(
            api_key=key,
            base_url="https://api.stlouisfed.org/fred",
            timeout=timeout,
            min_interval_seconds=kwargs.pop("min_interval_seconds", settings.min_interval_seconds["fred"]),
            **kwargs,
        )

    def observations(
        self,
        series_id: str,
        *,
        limit: int = 100000,
        sort_order: str = "asc",
    ) -> list[dict[str, Any]]:
        """The full observation history for one series, oldest first.

        Each observation carries `date` (the observation date) and `value`
        (a STRING — `"."` marks a missing value, which the staging layer
        filters out when casting to DOUBLE). FRED hands the key over the
        query string rather than a header.
        """
        payload = self.request(
            "GET",
            "/series/observations",
            params=build_query(
                {
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "limit": limit,
                    "sort_order": sort_order,
                }
            ),
        )
        self._raise_for_api_error(payload, series_id=series_id)
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, list):
            raise InvalidResponseError(f"{series_id}: expected 'observations' array")
        return observations

    @staticmethod
    def _raise_for_api_error(payload: Any, *, series_id: str) -> None:
        if isinstance(payload, dict) and payload.get("error_message"):
            raise APIError(f"{series_id}: {payload['error_message']}")