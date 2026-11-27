"""SEC EDGAR client: the XBRL API (data.sec.gov) and the filing archive
(www.sec.gov).

The XBRL API fills balance sheets that Finnhub's /stock/financials-reported
serves empty. EDGAR is where those filings come from: free, no API key, and
every fact is tagged with the accession number of the filing that reported
it, so a value can be matched to the exact Finnhub filing.

The archive serves the news digest's company stories (ingest.sec_filings):
the latest 8-K filings as an Atom feed, the daily form index, each filing's
index page and its documents, and the ticker -> CIK map.

    https://www.sec.gov/search-filings/edgar-application-programming-interfaces

SEC's fair-access rules: a User-Agent naming the caller with a contact email
(SEC_USER_AGENT, e.g. "Stockidence you@example.com"), and no more than 10
requests a second.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .base import BaseClient

WWW = "https://www.sec.gov"
_PAGE_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


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

    # --- the filing archive (www.sec.gov) --------------------------------

    def company_tickers(self) -> dict[str, Any]:
        """Every listed company's ticker, CIK and name:
        {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}."""
        payload = self.request("GET", f"{WWW}/files/company_tickers.json")
        return self._as_dict(payload, context="company_tickers")

    def current_filings(self, form: str = "8-K", start: int = 0, count: int = 100) -> str:
        """One page of the latest filings of `form`, newest first, as Atom
        XML. Each entry has the filer's name and CIK in its title, the items
        in its summary, the acceptance time and the filing index URL."""
        return self.request(
            "GET",
            f"{WWW}/cgi-bin/browse-edgar",
            params={
                "action": "getcurrent",
                "type": form,
                "company": "",
                "dateb": "",
                "owner": "include",
                "start": start,
                "count": count,
                "output": "atom",
            },
            headers={"Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8"},
            text=True,
        )

    def daily_form_index(self, day: date) -> str:
        """The day's form index (fixed-width text: form, company, CIK, date
        filed, path). NotFoundError on a day with no filings."""
        quarter = (day.month - 1) // 3 + 1
        return self.request(
            "GET",
            f"{WWW}/Archives/edgar/daily-index/{day.year}/QTR{quarter}/form.{day:%Y%m%d}.idx",
            headers={"Accept": "text/plain,*/*;q=0.8"},
            text=True,
        )

    def page(self, url: str) -> str:
        """An archive page (a filing index or one of its documents) as text."""
        if not url.startswith(f"{WWW}/"):
            raise ValueError(f"not an SEC archive URL: {url}")
        return self.request("GET", url, headers={"Accept": _PAGE_ACCEPT}, text=True)
