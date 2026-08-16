"""Unit tests for the provider clients.

HTTP transport is mocked so no network or real API keys are required.
Live-key smoke tests are intentionally excluded — the real API is exercised
by the Dagster jobs, not the test suite.
"""

from __future__ import annotations

import httpx
import pytest

from stockidence.clients.alpha_vantage import AlphaVantageClient
from stockidence.clients.base import APIError, InvalidResponseError, RateLimitError
from stockidence.clients.finnhub import FinnhubClient
from stockidence.clients.twelve_data import TwelveDataClient


def _mock_transport(monkeypatch, handler):
    """Route the client's httpx.request call through a fake handler."""
    def fake_request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        request = httpx.Request(method, url, **kwargs)
        return handler(request)

    monkeypatch.setattr(httpx, "request", fake_request)


def _client(monkeypatch, client_cls, handler, **kwargs):
    _mock_transport(monkeypatch, handler)
    return client_cls(api_key="test-key", retries=0, **kwargs)


class TestAlphaVantage:
    def test_gold_returns_series(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("function") == "GOLD"
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
            assert request.url.params.get("limit") == "100"
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