"""SEC EDGAR XBRL API client (data.sec.gov).

Fills balance sheets that Finnhub's /stock/financials-reported serves empty.
EDGAR is where those filings come from: free, no API key, and every fact is
tagged with the accession number of the filing that reported it, so a value
can be matched to the exact Finnhub filing.

    https://www.sec.gov/search-filings/edgar-application-programming-interfaces

SEC's fair-access rules: a User-Agent naming the caller with a contact email
(SEC_USER_AGENT, e.g. "Stockidence you@example.com"), and no more than 10
requests a second.
"""

from __future__ import annotations

from typing import Any

from .base import BaseClient


class SecEdgarClient(BaseClient):
    def __init__(
        self, *, user_agent: str | None = None, timeout: float = 60.0, **kwargs: Any
    ) -> None:
        from ...config import load_settings

        settings = load_settings()
        agent = user_agent or settings.sec_user_agent
        if not agent:
            raise ValueError("SEC_USER_AGENT is not set (SEC asks for a name and contact email)")
        self.user_agent = agent
        super().__init__(
            api_key="",
            base_url="https://data.sec.gov",
            timeout=timeout,
            min_interval_seconds=kwargs.pop(
                "min_interval_seconds", settings.min_interval_seconds["sec"]
            ),
            **kwargs,
        )

    def _default_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "User-Agent": self.user_agent}

    def company_facts(self, cik: str | int) -> dict[str, Any]:
        """Every XBRL fact the company has filed:
        facts → taxonomy (us-gaap, dei) → concept → units → [fact], where each
        fact carries end (and start, for flows), val, accn, form, filed."""
        payload = self.request("GET", f"/api/xbrl/companyfacts/CIK{int(cik):010d}.json")
        return self._as_dict(payload, context=f"companyfacts CIK{cik}")
