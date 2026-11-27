"""Government release feeds: the Federal Reserve, BLS, SEC press releases
and the FTC's competition releases.

Free and keyless: each is a public RSS feed. Requests carry the scraper's
honest user agent, or SEC_USER_AGENT for sec.gov (its fair-access rules ask
for a name and contact). robots.txt is checked by the caller
(ingest.agency_feeds) with the scraper's rules.
"""

from __future__ import annotations

from typing import Any

from .base import BaseClient

FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"


class AgencyFeedClient(BaseClient):
    def __init__(self, *, timeout: float = 30.0, **kwargs: Any) -> None:
        super().__init__(
            api_key="",
            base_url="",
            timeout=timeout,
            # a handful of feeds on different hosts, read once a run
            min_interval_seconds=kwargs.pop("min_interval_seconds", 1.0),
            **kwargs,
        )

    def _default_headers(self) -> dict[str, str]:
        return {"Accept": FEED_ACCEPT}

    def feed(self, url: str) -> str:
        """The feed's XML as text."""
        from urllib.parse import urlsplit

        from ..articles import user_agent_for

        host = urlsplit(url).netloc.lower()
        return self.request("GET", url, headers={"User-Agent": user_agent_for(host)}, text=True)
