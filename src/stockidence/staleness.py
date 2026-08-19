"""Staleness-aware gate in front of on-demand API calls.

The gate answers one question: for (endpoint, dimension), do we already
have data fresh enough to serve a request, or do we spend an API call?

Decision ordering (see `decide`):
  derived      -> never fetch (pure warehouse derivation)
  never fetched -> always fetch
  immutable    -> never refetch once landed
  TTL set      -> refetch when watermark age >= ttl
  conditional  -> delegate to a per-endpoint policy check against the
                  warehouse (the filing/calendar itself is the clock,
                  not wall time since last fetch)

Policy queries for conditional endpoints live in CONDITIONAL_CHECKS so
endpoint metadata stays declarative and the policies stay unit-testable.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from stockidence.endpoints import (
    Cadence,
    EndpointSpec,
    Provider,
    REGISTRY,
    Trigger,
    get_endpoint,
)
from stockidence.storage import RAW_SCHEMA, Warehouse, Watermark

# Filing-report grace: how long after a fiscal period ends we expect the
# report to exist before we consider our copy behind. 10-Ks are due ~60-75
# days after fiscal year end; a 75-day window covers annual filers.
FILING_GRACE_DAYS = 75


@dataclass(frozen=True)
class FetchDecision:
    """Result of one (endpoint, dimension) staleness check."""

    should_fetch: bool
    reason: str


def decide(
    spec: EndpointSpec,
    watermark: Watermark | None,
    now: datetime,
    conditional_fetch: bool | None = None,
) -> FetchDecision:
    """Pure staleness decision for one spec; no I/O.

    conditional_fetch is the *resolved* answer of the endpoint's policy
    check (staleness or not; None when no check applies).
    """
    if spec.trigger == Trigger.DERIVED:
        return FetchDecision(False, f"{spec.name}: derived table, no API call")

    if watermark is None:
        return FetchDecision(True, f"{spec.name}: never fetched for dimension")

    if spec.cadence == Cadence.IMMUTABLE:
        return FetchDecision(False, f"{spec.name}: immutable once published")

    if spec.ttl is not None:
        age = now - watermark.fetched_at
        reason = (
            f"{spec.name}: watermark age {age} >= ttl {spec.ttl}"
            if age >= spec.ttl
            else f"{spec.name}: fresh (age {age} < ttl {spec.ttl})"
        )
        return FetchDecision(age >= spec.ttl, reason)

    if spec.cadence == Cadence.CONDITIONAL:
        if conditional_fetch:
            return FetchDecision(True, f"{spec.name}: policy check says refetch")
        return FetchDecision(False, f"{spec.name}: policy check says current")

    return FetchDecision(False, f"{spec.name}: no fetch policy (scheduled/derived)")


def _period_end(year: int, quarter: int) -> date:
    """Calendar quarter-end date for (year, quarter)."""
    month = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
    return date(year, month, calendar.monthrange(year, month)[1])


def latest_expected_period(now: datetime, grace_days: int = FILING_GRACE_DAYS) -> tuple[int, int]:
    """Most recent (year, quarter) whose report we should already have.

    A period's report is expected once its end date plus the grace window
    has passed. Later periods are still inside their filing window, so
    their absence is not (yet) staleness.
    """
    y, q, _ = (now.year, now.month, now.day)
    candidates = [(y, 4), (y, 3), (y, 2), (y, 1), (y - 1, 4), (y - 1, 3)]
    for cy, cq in candidates:
        if _period_end(cy, cq) + timedelta(days=grace_days) <= now.date():
            return cy, cq
    return candidates[-1]


def check_insider_sentiment(warehouse: Warehouse, dimension_key: str, now: datetime) -> bool:
    """Refetch when the current calendar month has no row for the ticker.

    Insider disclosures are month-scoped; a ticker whose current month is
    absent in raw_insider_sentiment may have new activity. Dimension key
    is "AAPL" — the (year, month) grain is implied by `now`.
    """
    ticker = dimension_key.split("|")[0]
    with warehouse.connect(read_only=True) as con:
        count = con.execute(
            """
            SELECT COUNT(*) FROM raw.raw_insider_sentiment
            WHERE ticker = ? AND year = ? AND month = ?
            """,
            [ticker, now.year, now.month],
        ).fetchone()[0]
    return count == 0


def check_financials_reported(warehouse: Warehouse, dimension_key: str, now: datetime) -> bool:
    """Refetch when the reports holding is behind the filings we should have.

    Compares the latest (year, quarter) present in raw_financials_reported
    against the most recent period whose filing deadline has passed — the
    filing itself is the clock, not a day-count TTL.
    """
    ticker = dimension_key.split("|")[0]
    with warehouse.connect(read_only=True) as con:
        row = con.execute(
            """
            SELECT year, quarter FROM raw.raw_financials_reported
            WHERE ticker = ? ORDER BY year DESC, quarter DESC LIMIT 1
            """,
            [ticker],
        ).fetchone()
    if row is None:
        return True
    held_year, held_quarter = row
    expected_year, expected_quarter = latest_expected_period(now)
    if (held_year, held_quarter) < (expected_year, expected_quarter):
        return True
    return False


CONDITIONAL_CHECKS: dict[str, Callable[[Warehouse, str, datetime], bool]] = {
    "insider_sentiment": check_insider_sentiment,
    "financials_reported": check_financials_reported,
}


class StalenessGate:
    """Warehouse-backed staleness checks for on-demand endpoint calls."""

    def __init__(self, warehouse: Warehouse, now: datetime | None = None) -> None:
        self.warehouse = warehouse
        self._now = now  # injectable clock for tests

    def _now_utc(self, now: datetime | None) -> datetime:
        if now is not None:
            if now.tzinfo is None:
                return now.replace(tzinfo=timezone.utc)
            return now
        return datetime.now(timezone.utc)

    def _should_fetch(
        self,
        spec: EndpointSpec,
        dimension_key: str,
        now_dt: datetime,
    ) -> FetchDecision:
        watermark = self.warehouse.get_watermark(f"raw.{spec.artifacts[0]}", dimension_key)
        if watermark is None:
            watermark = self._grain_watermark(spec, dimension_key)
        if spec.cadence == Cadence.CONDITIONAL:
            check = CONDITIONAL_CHECKS.get(spec.name)
            if check is None:
                return FetchDecision(False, f"{spec.name}: no conditional check registered")
            conditional_fetch = True if watermark is None else check(self.warehouse, dimension_key, now_dt)
            return decide(spec, watermark, now_dt, conditional_fetch=conditional_fetch)
        return decide(spec, watermark, now_dt)

    def _grain_watermark(self, spec: EndpointSpec, dimension_key: str) -> Watermark | None:
        """Synthetic watermark from raw-row presence when dimension is a full grain.

        Watermarks are stored at dimension (ticker) granularity, but some
        endpoints — earnings_call_transcript — are requested at full grain,
        e.g. "AAPL|4|2026". For those, fall back to "do rows exist at this
        grain" so an immutable transcript is not refetched because its coarse
        watermark is shared with other quarters.
        """
        parts = dimension_key.split("|")
        if len(parts) < 2:
            return None
        cols = [name for name, _ in RAW_SCHEMA[spec.artifacts[0]]]
        prefix = cols[: len(parts)]
        conds = " AND ".join(f'"{c}" = ?' for c in prefix)
        with self.warehouse.connect(read_only=True) as con:
            row = con.execute(
                f"SELECT COUNT(*), MAX(fetched_at) FROM raw.\"{spec.artifacts[0]}\" WHERE {conds}",
                parts,
            ).fetchone()
        if row[0] == 0:
            return None
        fetched_at = row[1]
        if fetched_at is None or fetched_at.tzinfo is None:
            fetched_at = (fetched_at or datetime.now(timezone.utc)).replace(tzinfo=timezone.utc)
        return Watermark(spec.name, dimension_key, fetched_at)

    def should_fetch(self, endpoint_name: str, dimension_key: str, now: datetime | None = None) -> FetchDecision:
        """Decide whether (endpoint, dimension) needs a fresh API call."""
        spec = REGISTRY.get(endpoint_name) or get_endpoint(endpoint_name)
        if spec.provider == Provider.DERIVED:
            return decide(spec, None, self._now_utc(now))
        now_dt = self._now_utc(now or self._now)
        return self._should_fetch(spec, dimension_key, now_dt)