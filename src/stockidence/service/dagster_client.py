"""Push trigger for Dagster jobs: the frontend (via the API) launches runs
directly over GraphQL instead of queueing rows for a sensor to poll.

Nothing here raises into the rating flow — launch failures degrade to the
existing pending/refreshing UX and the next poll retries.
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from ..config import load_settings

REFRESH_JOB_NAME = "refresh_tickers"
REFRESH_OP_NAME = "refresh_tickers_op"

# Skip re-launching a ticker refreshed this recently. The profile page polls
# /api/rating every 10s while pending, so without this each poll would
# spawn a duplicate run.
_LAUNCH_COOLDOWN_SECONDS = 600.0
_last_launch: dict[str, float] = {}


def _client_and_config():
    from dagster_graphql import DagsterGraphQLClient

    parts = urlparse(load_settings().dagster_web_url)
    client = DagsterGraphQLClient(
        hostname=parts.hostname or "localhost",
        port_number=parts.port or 3000,
        use_https=parts.scheme == "https",
    )
    return client


def submit_refresh_run(tickers: list[str]) -> str:
    """Launch the refresh_tickers job for ``tickers``. Returns the run id.

    Raises RuntimeError when Dagster is unreachable or rejects the launch —
    callers map that to a 503.
    """
    clean = [t.strip().upper() for t in tickers if t.strip()]
    if not clean:
        raise ValueError("no tickers to refresh")
    run_config = {"ops": {REFRESH_OP_NAME: {"config": {"tickers": clean}}}}
    try:
        return _client_and_config().submit_job_execution(
            REFRESH_JOB_NAME, run_config=run_config
        )
    except Exception as exc:
        raise RuntimeError(f"Dagster launch failed: {exc}") from exc


def request_refresh(tickers: list[str]) -> str | None:
    """Best-effort launch with per-ticker cooldown. Never raises."""
    now = time.monotonic()
    due = [t for t in tickers if now - _last_launch.get(t.strip().upper(), 0.0) > _LAUNCH_COOLDOWN_SECONDS]
    if not due:
        return None
    try:
        run_id = submit_refresh_run(due)
    except Exception:
        return None
    for t in due:
        _last_launch[t.strip().upper()] = now
    return run_id
