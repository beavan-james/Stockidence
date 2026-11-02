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
  gap-fill     -> the policy check alone decides, even before the first
                  fetch: no gap in the other source, no call

Policy queries for conditional endpoints live in CONDITIONAL_CHECKS so
endpoint metadata stays declarative and the policies stay unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from .endpoints import (
    Cadence,
    EndpointSpec,
    Provider,
    REGISTRY,
    Trigger,
    get_endpoint,
)
from .raw_mapping import SEC_LOOKBACK_DAYS
from ..storage import RAW_SCHEMA, Warehouse, Watermark

# Filing-report grace: how long after a fiscal period ends we expect the
# report to exist before we consider our copy behind. 10-Qs are due 40-45
# days after quarter end; 75 days leaves room for late filers and for
# Finnhub's ingestion lag.
FILING_GRACE_DAYS = 75

# Length of one fiscal quarter: the longest calendar quarter. 52/53-week
# filers' 13- and 14-week quarters land within a week of it, well inside
# the filing grace.
QUARTER_DAYS = 92


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

    if spec.cadence == Cadence.GAP_FILL:
        if conditional_fetch:
            return FetchDecision(True, f"{spec.name}: gap check found filings to fill")
        return FetchDecision(False, f"{spec.name}: no gaps to fill")

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


def next_filing_due(newest_period_end: date, newest_quarter: int, grace_days: int = FILING_GRACE_DAYS) -> date:
    """Date by which the 10-Q after the newest filing held should exist.

    Counts from the company's own period end, so off-calendar fiscal years
    need no special case. The quarterly feed carries 10-Qs only: fiscal Q4
    is reported on the 10-K, so after a Q3 the next filing is the following
    Q1, two quarters out. A 10-K held from an older annual fetch (Finnhub's
    quarter 0) is followed by Q1 as usual. Until the due date, a missing
    filing is still inside its filing window, not staleness.
    """
    quarters_ahead = 2 if newest_quarter == 3 else 1
    return newest_period_end + timedelta(days=quarters_ahead * QUARTER_DAYS + grace_days)


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
    """Refetch when the filing after the newest one held should exist by now.

    The newest filing's own period end (payload endDate) is the clock, not
    a day-count TTL and not Finnhub's fiscal (year, quarter) labels: those
    run ahead of the calendar for off-calendar fiscal years (NVDA's FY2027
    Q1 ends April 2026), and no filer has a quarter-4 row, so comparing
    labels to calendar quarters skipped off-calendar filers for months and
    refetched every Dec-FY ticker from mid-March until its Q1 10-Q landed.
    """
    ticker = dimension_key.split("|")[0]
    with warehouse.connect(read_only=True) as con:
        row = con.execute(
            """
            SELECT period_end, quarter FROM (
                SELECT TRY_CAST(substr(json_extract_string(payload, '$.endDate'), 1, 10) AS DATE) AS period_end,
                       quarter
                FROM raw.raw_financials_reported
                WHERE ticker = ?
            )
            WHERE period_end IS NOT NULL
            ORDER BY period_end DESC, quarter LIMIT 1
            """,
            [ticker],
        ).fetchone()
    if row is None:
        return True
    period_end, quarter = row
    return next_filing_due(period_end, quarter) <= now.date()


def check_sec_balance_sheets(warehouse: Warehouse, dimension_key: str, now: datetime) -> bool:
    """Fetch when Finnhub has landed a filing with an empty balance sheet
    since the ticker's last SEC fetch, and SEC hasn't filled it yet.

    The clock is Finnhub's deliveries, not wall time: a ticker whose filings
    are complete never spends an SEC call, and a filing SEC didn't have gets
    another try each time Finnhub refetches. Filings older than the SEC
    lookback are never landed from SEC, so they don't count as gaps.
    """
    ticker = dimension_key.split("|")[0]
    cutoff = now.date() - timedelta(days=SEC_LOOKBACK_DAYS)
    with warehouse.connect(read_only=True) as con:
        gaps = con.execute(
            """
            SELECT COUNT(*) FROM raw.raw_financials_reported f
            WHERE f.ticker = ?
              AND COALESCE(json_array_length(json_extract(f.payload, '$.report.bs')), 0) = 0
              AND TRY_CAST(substr(json_extract_string(f.payload, '$.filedDate'), 1, 10) AS DATE) >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM raw.raw_sec_balance_sheets s
                  WHERE s.ticker = f.ticker
                    AND s.accession_number = json_extract_string(f.payload, '$.accessNumber'))
              AND f.fetched_at > COALESCE(
                  (SELECT MAX(fetched_at) FROM raw.raw_sec_balance_sheets WHERE ticker = f.ticker),
                  TIMESTAMPTZ '1970-01-01 00:00:00+00')
            """,
            [ticker, cutoff],
        ).fetchone()[0]
    return gaps > 0


CONDITIONAL_CHECKS: dict[str, Callable[[Warehouse, str, datetime], bool]] = {
    "insider_sentiment": check_insider_sentiment,
    "financials_reported": check_financials_reported,
    "sec_balance_sheets": check_sec_balance_sheets,
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
        if spec.cadence in (Cadence.CONDITIONAL, Cadence.GAP_FILL):
            check = CONDITIONAL_CHECKS.get(spec.name)
            if check is None:
                return FetchDecision(False, f"{spec.name}: no conditional check registered")
            # a gap-fill endpoint asks its check even before the first fetch
            if watermark is None and spec.cadence == Cadence.CONDITIONAL:
                conditional_fetch = True
            else:
                conditional_fetch = check(self.warehouse, dimension_key, now_dt)
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