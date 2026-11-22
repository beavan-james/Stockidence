"""Unit tests for the provider clients.

HTTP transport is mocked so no network or real API keys are required.
Live-key smoke tests are intentionally excluded — the real API is exercised
by the Dagster jobs, not the test suite.
"""

from __future__ import annotations

import httpx
import pytest

from stockidence.ingest.clients.alpha_vantage import AlphaVantageClient
from stockidence.ingest.clients.base import APIError, InvalidResponseError, RateLimitError
from stockidence.ingest.clients.finnhub import FinnhubClient
from stockidence.ingest.clients.twelve_data import TwelveDataClient


def _mock_transport(monkeypatch, handler):
    """Route the client's httpx.request call through a fake handler."""
    def fake_request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        kwargs["follow_redirects"] = kwargs.get("follow_redirects", False)
        kwargs.pop("follow_redirects", None)
        request = httpx.Request(method, url, **kwargs)
        return handler(request)

    monkeypatch.setattr(httpx, "request", fake_request)


def _client(monkeypatch, client_cls, handler, **kwargs):
    _mock_transport(monkeypatch, handler)
    # tests must be hermetic: no shared pace file, no provider spacing
    kwargs.setdefault("pace_file", None)
    kwargs.setdefault("min_interval_seconds", 0.0)
    kwargs.setdefault("retries", 0)
    return client_cls(api_key="test-key", **kwargs)


class TestAlphaVantage:
    def test_gold_returns_series(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("function") == "GOLD_SILVER_HISTORY"
            assert request.url.params.get("symbol") == "GOLD"
            assert request.url.params.get("interval") == "monthly"
            assert request.url.params.get("apikey") == "test-key"
            return httpx.Response(200, json={"name": "gold", "data": [{"date": "2026-07-01", "value": "3448.12"}]})

        client = _client(monkeypatch, AlphaVantageClient, handler)
        result = client.gold()
        assert result["data"][0]["value"] == "3448.12"

    def test_top_gainers_losers(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("function") == "TOP_GAINERS_LOSERS"
            return httpx.Response(200, json={"top_gainers": [], "top_losers": []})

        client = _client(monkeypatch, AlphaVantageClient, handler)
        assert client.top_gainers_losers() == {"top_gainers": [], "top_losers": []}

    def test_news_sentiment_passes_filters(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("function") == "NEWS_SENTIMENT"
            assert request.url.params.get("tickers") == "AAPL,MSFT"
            assert request.url.params.get("limit") == "1000"
            return httpx.Response(200, json={"feed": []})

        client = _client(monkeypatch, AlphaVantageClient, handler)
        assert client.market_news(tickers="AAPL,MSFT") == {"feed": []}

    def test_rate_limit_note_raises(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Note": "Thanks for using Alpha Vantage!"})

        client = _client(monkeypatch, AlphaVantageClient, handler)
        with pytest.raises(RateLimitError):
            client.gold()

    def test_error_message_raises(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Error Message": "Invalid API call"})

        client = _client(monkeypatch, AlphaVantageClient, handler)
        with pytest.raises(APIError):
            client.gold()


class TestFinnhub:
    def test_quote_includes_auth_header(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("X-Finnhub-Token") == "test-key"
            return httpx.Response(200, json={"c": 261.74, "h": 263.31, "l": 260.68})

        client = _client(monkeypatch, FinnhubClient, handler)
        assert client.quote("AAPL")["c"] == 261.74

    def test_peers_returns_list(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["AAPL", "MSFT"])

        client = _client(monkeypatch, FinnhubClient, handler)
        assert client.peers("AAPL") == ["AAPL", "MSFT"]

    def test_peers_rejects_dict(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": "shape"})

        client = _client(monkeypatch, FinnhubClient, handler)
        with pytest.raises(InvalidResponseError):
            client.peers("AAPL")

    def test_http_429_raises_rate_limit(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="rate limited")

        client = _client(monkeypatch, FinnhubClient, handler)
        with pytest.raises(RateLimitError):
            client.quote("AAPL")


class TestSharedPacing:
    def test_pace_file_spaces_calls_across_client_instances(
            self, monkeypatch, tmp_path):
        """Two fresh clients (as separate Dagster runs would be) sharing a
        pace file must wait out the interval between their calls."""
        import time as time_mod

        from stockidence.ingest.clients.base import BaseClient

        pace_file = tmp_path / "pace"
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": True})

        _mock_transport(monkeypatch, handler)
        monkeypatch.setattr(time_mod, "sleep", sleeps.append)
        monkeypatch.setattr(time_mod, "time", lambda: 1_000.0)

        common = dict(base_url="https://example.test",
                      min_interval_seconds=60.0, pace_file=str(pace_file))
        first = BaseClient(api_key="k", **common)
        second = BaseClient(api_key="k", **common)

        first.request("GET", "/a")
        # second client's process has no memory of the first call; only the
        # shared file can tell it to wait
        second.request("GET", "/b")
        assert sleeps and sleeps[0] == pytest.approx(60.0)

    def test_pace_file_records_wall_clock(self, tmp_path):
        from stockidence.ingest.clients.base import BaseClient

        pace_file = tmp_path / "pace"
        client = BaseClient(api_key="k", base_url="https://example.test",
                            min_interval_seconds=0.0, pace_file=str(pace_file))
        client._pace_shared()
        written = float(pace_file.read_text().strip())
        assert written > 1_500_000_000  # plausible epoch seconds

    def test_rate_limit_error_is_retried(self, monkeypatch):
        calls = {"n": 0}
        sleeps: list[float] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError("AV: spread out your free API requests")
            return httpx.Response(200, json={"ok": True})

        import stockidence.ingest.clients.base as base_mod
        monkeypatch.setattr(base_mod.time, "sleep", sleeps.append)
        client = _client(monkeypatch, AlphaVantageClient, handler,
                         retries=2, backoff_seconds=1.0)
        assert client.gold()["ok"] is True
        assert calls["n"] == 2
        assert sleeps == [12.0]  # rate-limit backoff is 12x the base


class TestTwelveData:
    def test_time_series_returns_values(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("apikey") == "test-key"
            assert request.url.params.get("symbol") == "AAPL"
            assert request.url.params.get("interval") == "1day"
            assert request.url.params.get("adjust") == "splits"
            return httpx.Response(
                200,
                json={
                    "meta": {"symbol": "AAPL", "interval": "1day"},
                    "values": [{"datetime": "2026-08-14", "open": "1", "close": "2"}],
                    "status": "ok",
                },
            )

        client = _client(monkeypatch, TwelveDataClient, handler)
        result = client.time_series("AAPL", interval="1day")
        assert result["values"][0]["datetime"] == "2026-08-14"

    def test_error_status_raises_api_error(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "error", "message": "bad symbol", "code": 400})

        client = _client(monkeypatch, TwelveDataClient, handler)
        with pytest.raises(APIError):
            client.time_series("NOPE")

    def test_rate_limit_status_raises(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "error", "message": "out of credits", "code": 429})

        client = _client(monkeypatch, TwelveDataClient, handler)
        with pytest.raises(RateLimitError):
            client.time_series("AAPL")