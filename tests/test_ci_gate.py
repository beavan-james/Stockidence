"""Tests for scripts/ci_gate.py, the CI check auto-deploy.sh runs before deploying."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci_gate.py"
_spec = importlib.util.spec_from_file_location("ci_gate", _PATH)
assert _spec is not None and _spec.loader is not None
ci_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_gate)

SHA = "a" * 40
OTHER_SHA = "b" * 40


def _run(run_id=1, status="completed", conclusion="success", sha=SHA, event="push"):
    return {
        "id": run_id,
        "head_sha": sha,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}",
    }


def _payload(*runs):
    return {"total_count": len(runs), "workflow_runs": list(runs)}


def test_success_deploys():
    assert ci_gate.verdict(_payload(_run()), SHA) == (
        "success",
        "CI passed: https://github.com/o/r/actions/runs/1",
    )


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "requested", "pending"])
def test_unfinished_run_is_pending(status):
    state, detail = ci_gate.verdict(_payload(_run(status=status, conclusion=None)), SHA)
    assert state == "pending"
    assert status in detail


def test_no_run_yet_is_pending():
    assert ci_gate.verdict(_payload(), SHA) == ("pending", "no CI run yet")


@pytest.mark.parametrize(
    "conclusion",
    ["failure", "cancelled", "timed_out", "startup_failure", "action_required", "skipped"],
)
def test_finished_without_passing_is_failed(conclusion):
    state, detail = ci_gate.verdict(_payload(_run(conclusion=conclusion)), SHA)
    assert state == "failed"
    assert detail == f"CI {conclusion}: https://github.com/o/r/actions/runs/1"


def test_other_commits_and_pull_request_runs_are_ignored():
    payload = _payload(
        _run(run_id=3, sha=OTHER_SHA),
        _run(run_id=2, event="pull_request"),
    )
    assert ci_gate.verdict(payload, SHA) == ("pending", "no CI run yet")


@pytest.mark.parametrize(
    ("older", "newer", "expected"),
    [("failure", "success", "success"), ("success", "failure", "failed")],
)
def test_newest_run_of_the_commit_decides(older, newer, expected):
    # Listed oldest first, so this doesn't lean on the API's ordering.
    payload = _payload(_run(run_id=1, conclusion=older), _run(run_id=2, conclusion=newer))
    assert ci_gate.verdict(payload, SHA)[0] == expected


@pytest.mark.parametrize("payload", [{}, {"workflow_runs": None}, [], "nope"])
def test_malformed_payload_raises(payload):
    with pytest.raises(TypeError):
        ci_gate.verdict(payload, SHA)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, outcome):
    """Make urlopen return `outcome` (a dict or bytes body) or raise it."""
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        if isinstance(outcome, BaseException):
            raise outcome
        body = outcome if isinstance(outcome, bytes) else json.dumps(outcome).encode()
        return _Response(body)

    monkeypatch.setattr(ci_gate, "urlopen", fake_urlopen)
    return seen


def test_check_asks_for_push_runs_of_the_commit_on_master(monkeypatch):
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    seen = _serve(monkeypatch, _payload(_run()))
    assert ci_gate.check(SHA)[0] == "success"
    assert seen["url"] == (
        "https://api.github.com/repos/beavan-james/Stockidence/actions/workflows/ci.yml/runs"
        f"?head_sha={SHA}&event=push&branch=master&per_page=20"
    )


def test_check_reports_unreachable_api(monkeypatch):
    _serve(monkeypatch, URLError("[Errno 8] nodename nor servname provided"))
    assert ci_gate.check(SHA) == ("error", "[Errno 8] nodename nor servname provided")


def test_check_reports_timeout(monkeypatch):
    _serve(monkeypatch, TimeoutError("timed out"))
    assert ci_gate.check(SHA) == ("error", "timed out")


@pytest.mark.parametrize(
    ("code", "message"),
    [(403, "API rate limit exceeded for 203.0.113.7."), (404, "Not Found")],
)
def test_check_reports_http_errors_with_githubs_message(monkeypatch, code, message):
    body = io.BytesIO(json.dumps({"message": message}).encode())
    _serve(monkeypatch, HTTPError("url", code, "error", {}, body))  # type: ignore[arg-type]
    assert ci_gate.check(SHA) == ("error", f"HTTP {code} {message}")


def test_check_reports_non_json_body(monkeypatch):
    _serve(monkeypatch, b"<html>Unicorn!</html>")
    state, detail = ci_gate.check(SHA)
    assert state == "error"
    assert detail.startswith("unreadable response")


def test_check_reports_unexpected_shape(monkeypatch):
    _serve(monkeypatch, {"message": "Moved Permanently"})
    state, detail = ci_gate.check(SHA)
    assert state == "error"
    assert detail.startswith("unexpected response")


def test_main_prints_one_line(monkeypatch, capsys):
    _serve(monkeypatch, _payload(_run(status="in_progress", conclusion=None)))
    assert ci_gate.main(["ci_gate.py", SHA]) == 0
    assert (
        capsys.readouterr().out == "pending CI in_progress: https://github.com/o/r/actions/runs/1\n"
    )


def test_main_rejects_a_short_sha(capsys):
    ci_gate.main(["ci_gate.py", "abc123"])
    assert capsys.readouterr().out.startswith("error usage")
