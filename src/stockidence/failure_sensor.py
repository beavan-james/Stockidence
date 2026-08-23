"""Failure capture: every failed pipeline run lands in control.pipeline_failures.

Dagster's own run history lives in its instance storage, not the warehouse,
and this deployment keeps no persistent DAGSTER_HOME history - so once the
webserver restarts there is nothing left to query. A daemon-run failure
sensor closes that gap: it appends each failure to the warehouse, which the
frontend health panel reads. The sensor is a catch-all: it fires for
scheduled jobs, sensor-triggered on-demand runs, and manual launches alike.
"""

from datetime import datetime, timedelta, timezone

from dagster import RunFailureSensorContext, run_failure_sensor

from .storage import Warehouse

RETENTION_DAYS = 30


def record_failure(
    warehouse: Warehouse,
    run_id: str,
    job_name: str,
    failed_at: datetime,
    error_message: str | None = None,
) -> None:
    """Insert one failure row; re-fires for the same run_id are no-ops."""
    with warehouse.connect() as con:
        con.execute(
            """
            INSERT INTO control.pipeline_failures
                (run_id, job_name, failed_at, error_message)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (run_id) DO NOTHING
            """,
            [run_id, job_name, failed_at.isoformat(), error_message],
        )
        con.execute(
            """
            DELETE FROM control.pipeline_failures
            WHERE failed_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
            """,
        )


def _error_message(context: RunFailureSensorContext) -> str | None:
    try:
        return context.failure_event.event_specific_data.error.to_string()
    except Exception:
        return None


@run_failure_sensor
def pipeline_failure_sensor(context: RunFailureSensorContext) -> None:
    """Daemon-side catch-all: write any failed run into the warehouse."""
    record_failure(
        Warehouse(),
        run_id=context.dagster_run.run_id,
        job_name=context.dagster_run.job_name,
        failed_at=datetime.now(timezone.utc),
        error_message=_error_message(context),
    )
