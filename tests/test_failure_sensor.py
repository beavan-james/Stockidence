"""Tests for the failure-capture sensor and its warehouse table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stockidence.failure_sensor import record_failure
from stockidence.storage import Warehouse


def _make_wh(tmp_path):
    wh = Warehouse(tmp_path / "fail.duckdb")
    wh.init_schema()
    return wh


def test_init_schema_creates_pipeline_failures(tmp_path):
    wh = _make_wh(tmp_path)
    tables = {
        row[0]
        for row in wh.connect(read_only=True)
        .execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'control'"
        )
        .fetchall()
    }
    assert "pipeline_failures" in tables


def test_record_failure_inserts_and_dedups_on_run_id(tmp_path):
    wh = _make_wh(tmp_path)
    now = datetime.now(timezone.utc)

    record_failure(wh, "run-1", "daily_ingest", now, "boom")
    # re-fire for the same run (e.g. sensor re-evaluation) must not duplicate
    record_failure(wh, "run-1", "daily_ingest", now, "boom")

    rows = wh.connect(read_only=True).execute(
        "SELECT run_id, job_name, error_message FROM control.pipeline_failures"
    ).fetchall()
    assert rows == [("run-1", "daily_ingest", "boom")]


def test_record_failure_prunes_past_retention(tmp_path):
    wh = _make_wh(tmp_path)
    now = datetime.now(timezone.utc)

    record_failure(wh, "old", "daily_ingest", now - timedelta(days=31))
    record_failure(wh, "fresh", "weekdays_ingest", now - timedelta(days=2))

    remaining = [
        r[0] for r in wh.connect(read_only=True)
        .execute("SELECT run_id FROM control.pipeline_failures")
        .fetchall()
    ]
    assert remaining == ["fresh"]


def test_failure_sensor_registered_in_definitions():
    from stockidence.definitions import defs
    from stockidence.failure_sensor import pipeline_failure_sensor

    assert pipeline_failure_sensor.name in {s.name for s in defs.sensors}
