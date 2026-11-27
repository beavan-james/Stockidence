"""S&P 500 membership history (fja05680/sp500 on GitHub).

S&P's own constituent history is a paid product. This community-maintained
list rebuilds it from the index's published changes: one row per spell a
ticker spent in the index since 1996, with a blank end date for a current
member. Free, keyless and about 30 KB, so one call fetches all of it.

    https://github.com/fja05680/sp500

The list is keyed by ticker, not company: a rename ends one ticker's spell
and starts the next (MMC -> MRSH on 2026-01-14), and a reused ticker carries
two companies' spells. staging/sp500_membership.py resolves both.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from .base import BaseClient, InvalidResponseError

COLUMNS = ("ticker", "start_date", "end_date")


class Sp500HistoryClient(BaseClient):
    def __init__(self, *, timeout: float = 30.0, **kwargs: Any) -> None:
        super().__init__(
            api_key="",
            base_url="https://raw.githubusercontent.com/fja05680/sp500/master",
            timeout=timeout,
            **kwargs,
        )

    def _default_headers(self) -> dict[str, str]:
        return {"Accept": "text/csv, text/plain"}

    def _parse(self, resp: httpx.Response) -> Any:
        return resp.text

    def membership(self) -> list[dict[str, str]]:
        """Every membership spell: ticker, start_date and end_date as the
        file has them (ISO dates; end_date is "" for a current member)."""
        text = self.request("GET", "/sp500_ticker_start_end.csv")
        return parse_membership_csv(text)


def parse_membership_csv(text: str | None) -> list[dict[str, str]]:
    """Rows of the membership CSV, refusing a file that lost its columns or
    its rows (a moved file can come back as an HTML page or an empty body)."""
    reader = csv.DictReader(io.StringIO(text or ""))
    missing = set(COLUMNS) - set(reader.fieldnames or ())
    if missing:
        raise InvalidResponseError(
            f"sp500 membership: expected columns {COLUMNS}, got {reader.fieldnames}"
        )
    rows = [
        {col: (row[col] or "").strip() for col in COLUMNS}
        for row in reader
        if (row["ticker"] or "").strip()
    ]
    if not rows:
        raise InvalidResponseError("sp500 membership: the file has no rows")
    return rows
