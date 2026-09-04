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
        min_interval_seconds: float = 0.0,
        pace_file: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._last_call_at = 0.0
        self.pace_file = pace_file

    def _pace(self) -> None:
        """Enforce a per-provider minimum interval between calls (free-tier
        limits are coarser than HTTP 429 handling can paper over)."""
        if self.min_interval_seconds <= 0:
            return
        if self.pace_file:
            self._pace_shared()
            return
        wait = self.min_interval_seconds - (time.monotonic() - self._last_call_at)
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    def _pace_shared(self) -> None:
        """Cross-process pacing via an flock-guarded timestamp file.

        In-memory pacing is per-instance, and every Dagster run is its own
        process with a fresh client — a bulk sensor tick can launch many runs
        at once and stampede a provider's burst limit (seen live with Alpha
        Vantage transcripts). The lockfile makes all processes on this
        machine share one call schedule.
        """
        import fcntl
        import os

        directory = os.path.dirname(self.pace_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.pace_file, "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read().strip()
                try:
                    last = float(content)
                except ValueError:
                    last = 0.0
                wait = self.min_interval_seconds - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
                fh.seek(0)
                fh.truncate()
                fh.write(str(time.time()))
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

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
            except RateLimitError as exc:
                # burst collisions heal with patience; a genuinely exhausted
                # daily quota will fail all attempts and surface to Dagster
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff_seconds * 12 * (attempt + 1))
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
        self._pace()
        url = f"{self.base_url}{path}"
        final_headers = {**self._default_headers(), **(headers or {})}
        resp = httpx.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=final_headers,
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._raise_for_status(resp)
        return self._parse(resp)

    def _default_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def _redact_url(self, url: httpx.URL) -> str:
        params = [
            (k, "***" if k == "api_key" else v) for k, v in url.params.multi_items()
        ]
        return str(url.copy_with(params=params))

    def _parse(self, resp: httpx.Response) -> Any:
        if not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise InvalidResponseError(f"Non-JSON response from {self._redact_url(resp.url)}: {resp.text[:200]}") from exc

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code in (429,):
            raise RateLimitError(f"Rate limited by {self.base_url} (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise APIError(f"HTTP {resp.status_code} from {self._redact_url(resp.url)}: {resp.text[:300]}")

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