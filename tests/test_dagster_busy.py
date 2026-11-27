"""Tests for scripts/dagster_busy.py, the run check auto-deploy.sh runs before deploying."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dagster_busy.py"
_spec = importlib.util.spec_from_file_location("dagster_busy", _PATH)
assert _spec is not None and _spec.loader is not None
dagster_busy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dagster_busy)

NOW = 1_800_000_000.0


def _payload(*runs, typename="Runs"):
    return {"data": {"runsOrError": {"__typename": typename, "results": list(runs)}}}


def _run(job="weekly_model_refresh", age_s=600.0):
    return {"runId": "43ad03eb-c09d", "jobName": job, "creationTime": NOW - age_s}


def test_no_runs_is_idle():
    assert dagster_busy.verdict(_payload(), NOW)[0] == "idle"


def test_a_running_job_holds_the_deploy():
    state, detail = dagster_busy.verdict(_payload(_run()), NOW)
    assert state == "busy" and "weekly_model_refresh 43ad03eb" in detail


def test_a_run_left_started_for_over_a_day_is_ignored():
    assert dagster_busy.verdict(_payload(_run(age_s=2 * 86400)), NOW)[0] == "idle"


def test_a_graphql_error_is_not_read_as_idle():
    with pytest.raises(ValueError):
        dagster_busy.verdict(_payload(typename="PythonError"), NOW)


def test_an_unreachable_webserver_lets_the_deploy_through(monkeypatch):
    monkeypatch.setenv("DAGSTER_GRAPHQL_URL", "http://127.0.0.1:9/graphql")
    assert dagster_busy.check()[0] == "idle"
