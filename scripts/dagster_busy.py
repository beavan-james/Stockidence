"""Ask the local Dagster webserver whether any run is in progress.

auto-deploy.sh runs this before it deploys, because a deploy recreates every
container built from the shared backend image, which kills whatever run is in
flight (a backfill, the weekly or quarterly retrain):

    python3 scripts/dagster_busy.py

It prints one line, "<state> <detail>":

    idle   no run is queued or running (or the webserver isn't up): deploy
    busy   at least one run is queued or running: wait for the next cron pass
    error  the webserver answered with something this can't read: don't deploy

A run that has sat in progress for longer than STALE_AFTER_S is taken as dead
(a run killed by an earlier deploy stays STARTED in the UI until someone marks
it failed), so it can't hold deploys back forever. Standard library only, and
no syntax newer than 3.8, like ci_gate.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TIMEOUT_S = 10
# Longer than any real run (the quarterly refresh takes hours, not a day).
STALE_AFTER_S = 24 * 3600

IN_PROGRESS = ["QUEUED", "NOT_STARTED", "STARTING", "STARTED", "CANCELING"]
QUERY = (
    "query { runsOrError(filter: {statuses: [" + ", ".join(IN_PROGRESS) + "]}) { __typename"
    " ... on Runs { results { runId jobName creationTime } } } }"
)


def verdict(payload: object, now: float) -> tuple[str, str]:
    """Turn a runsOrError response into (state, detail)."""
    if not isinstance(payload, dict):
        raise TypeError("response is not an object")
    runs_or_error = payload["data"]["runsOrError"]
    if runs_or_error.get("__typename") != "Runs":
        raise ValueError(f"runsOrError returned {runs_or_error.get('__typename')}")
    live = [
        run
        for run in runs_or_error["results"]
        if now - float(run.get("creationTime") or now) < STALE_AFTER_S
    ]
    if not live:
        return "idle", "no run in progress"
    names = ", ".join(f"{run['jobName']} {run['runId'][:8]}" for run in live)
    return "busy", names


def graphql_url() -> str:
    # The webserver publishes its port on the host's loopback only (docker-compose.yml).
    return os.environ.get("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3000/graphql")


def check() -> tuple[str, str]:
    """Ask the webserver and judge the answer; never raises."""
    request = Request(
        graphql_url(),
        data=json.dumps({"query": QUERY}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.load(response)
    except HTTPError as exc:
        return "error", f"HTTP {exc.code}"
    except (OSError, HTTPException) as exc:
        # Refused or unreachable: Dagster isn't up, so no run can be killed,
        # and a deploy is what would bring it back.
        return "idle", f"webserver unreachable ({getattr(exc, 'reason', exc)})"
    except ValueError as exc:
        return "error", f"unreadable response: {exc}"
    try:
        return verdict(payload, time.time())
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return "error", f"unexpected response: {exc}"


def main() -> int:
    state, detail = check()
    print(f"{state} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
