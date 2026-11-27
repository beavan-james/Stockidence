"""Ask GitHub whether the CI workflow passed for one commit.

auto-deploy.sh runs this before it deploys a new origin/master commit:

    python3 scripts/ci_gate.py <full commit sha>

It prints one line, "<state> <detail>", and the script acts on the state:

    success  CI passed for this exact commit: deploy
    pending  CI is queued or running, or its run doesn't exist yet: retry next time
    failed   CI finished without passing (failure, cancelled, timed out...): don't deploy
    error    GitHub couldn't be asked or gave an answer this can't read: don't deploy

Only runs of .github/workflows/ci.yml started by a push to master count, so a
pull-request run of the same commit isn't taken as proof.

The repository is public, so the unauthenticated REST API is enough (60
requests an hour per IP; cron asks at most 12 times an hour, and only while a
new commit waits). Standard library only, and no syntax newer than 3.8: the
host has python3, but not necessarily jq or curl or a recent Python.
"""

from __future__ import annotations

import json
import os
import sys
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = "beavan-james/Stockidence"
WORKFLOW = "ci.yml"
BRANCH = "master"
TIMEOUT_S = 15


def verdict(payload: object, sha: str) -> tuple[str, str]:
    """Turn a list-workflow-runs response into (state, detail)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        raise TypeError("no workflow_runs list in the response")
    runs = [
        run
        for run in payload["workflow_runs"]
        if run.get("head_sha") == sha and run.get("event") == "push"
    ]
    if not runs:
        # GitHub creates the run a few seconds after the push.
        return "pending", "no CI run yet"
    # The same commit pushed twice has two runs; the newest one decides.
    run = max(runs, key=lambda r: r["id"])
    url = run.get("html_url", "")
    if run.get("status") != "completed":
        return "pending", f"CI {run.get('status')}: {url}"
    if run.get("conclusion") == "success":
        return "success", f"CI passed: {url}"
    return "failed", f"CI {run.get('conclusion')}: {url}"


def runs_url(sha: str) -> str:
    # GITHUB_API_URL is GitHub's own name for the API base; tests point it at a stub.
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    query = urlencode({"head_sha": sha, "event": "push", "branch": BRANCH, "per_page": 20})
    return f"{base}/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?{query}"


def check(sha: str) -> tuple[str, str]:
    """Fetch the CI runs for `sha` and judge them; never raises."""
    request = Request(
        runs_url(sha),
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "auto-deploy-ci-gate",  # GitHub rejects requests without one
        },
    )
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.load(response)
    except HTTPError as exc:
        # A 404 means the workflow file isn't on the default branch; a 403 is
        # usually the rate limit. GitHub explains either in "message".
        try:
            message = json.load(exc).get("message", "")
        except Exception:
            message = ""
        return "error", f"HTTP {exc.code} {message}".rstrip()
    except (OSError, HTTPException) as exc:  # DNS, refused, TLS, timeout, dropped connection
        return "error", str(getattr(exc, "reason", exc))
    except ValueError as exc:  # body isn't JSON
        return "error", f"unreadable response: {exc}"
    try:
        return verdict(payload, sha)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return "error", f"unexpected response: {exc}"


def main(argv: list[str]) -> int:
    if len(argv) != 2 or len(argv[1]) != 40:
        print("error usage: ci_gate.py <full 40-character commit sha>")
        return 2
    state, detail = check(argv[1])
    print(f"{state} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
