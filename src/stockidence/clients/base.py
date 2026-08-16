"""Shared HTTP plumbing for the stock data clients."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx


class StockidenceError(RuntimeError):
    """Base error for the pipeline."""


class APIError(StockidenceError):
    """A provider returned an error response."""


class RateLimitError(StockidenceError):
    """A provider returned a rate-limit response."""


class InvalidResponseError(StockidenceError):
    """A provider returned a response that could not be parsed."""


class BaseClient:
    """Small httpx wrapper shared by all providers.

    Handles auth, JSON parsing, and the two failure modes that matter for a
    free-tier pipeline: HTTP errors and provider-specific rate-limit bodies.
    """

    def __init__(
        self,
        *,
        api_key: tuple[str, ...] | str,
        base_url: str,
        timeout: float = 30.0,
        retries: int = 2,
        backoff_seconds: float = 1.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._request_once(method, path, params=params, json_body=json_body, headers=headers)
            except (APIError, InvalidResponseError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff_seconds * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        headers: dict[str, str] | None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        final_headers = {**self._default_headers(), **(headers or {})}
        resp = httpx.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=final_headers,
            timeout=self.timeout,
        )
        self._raise_for_status(resp)
        return self._parse(resp)

    def _default_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _parse(self, resp: httpx.Response) -> Any:
        if not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(f"Non-JSON response from {resp.url}: {resp.text[:200]}") from exc

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code in (429,):
            raise RateLimitError(f"Rate limited by {self.base_url} (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise APIError(f"HTTP {resp.status_code} from {resp.url}: {resp.text[:300]}")

    def _as_dict(self, payload: Any, *, context: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise InvalidResponseError(f"{context}: expected object, got {type(payload).__name__}")
        return payload


def build_query(params: dict[str, Any]) -> dict[str, str]:
    """Flatten optional/None values out of a params dict for query strings."""
    return {k: v for k, v in params.items() if v is not None}


def retry(
    retries: int = 2,
    backoff_seconds: float = 1.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry decorator for individual client methods.

    Range: transient APIError only; rate-limit errors propagate so the caller
    (cache/orchestration layer) can decide whether to back off globally.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except RateLimitError:
                    raise
                except APIError:
                    if attempt >= retries:
                        raise
                    time.sleep(backoff_seconds * (attempt + 1))
            raise RuntimeError("unreachable")

        return wrapper

    return decorator