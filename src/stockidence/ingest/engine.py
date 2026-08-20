"""Ingestion engine: gate → client call → normalize → land → watermark.

The engine is the single entry point for both ingestion paths AGENTS.md
describes:

  - On-demand: `ingest_on_demand(endpoint, dimension)` consult the staleness
    gate, spend an API call only when the cache is stale, land rows, and bump
    the watermark. This is the hot path behind a user's ticker lookup.
  - Scheduled: `ingest_scheduled(endpoint)` ignore the gate — the Dagster
    schedule already decided it's time — then normalize and land. Watermarks
    are still updated so on-demand lookups can reuse the result.

Every endpoint resolves to a client method via the REGISTRY, and every
response shape resolves to artifact rows via NORMALIZERS — the engine itself
holds no per-endpoint response logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .clients.alpha_vantage import AlphaVantageClient
from .clients.finnhub import FinnhubClient
from .clients.twelve_data import TwelveDataClient
from .endpoints import EndpointSpec, Provider, get_endpoint
from .raw_mapping import normalize_for
from .staleness import FetchDecision, StalenessGate
from ..storage import Warehouse

_PROVIDER_CLIENTS = {
    Provider.FINNHUB: FinnhubClient,
    Provider.TWELVE_DATA: TwelveDataClient,
    Provider.ALPHA_VANTAGE: AlphaVantageClient,
}

_SCHEDULED_DEFAULT_WINDOW_DAYS = 45


@dataclass(frozen=True)
class IngestResult:
    """Outcome of one ingestion attempt."""

    endpoint: str
    dimension_key: str
    fetched: bool
    reason: str
    rows_written: int
    high_watermark: str | None = None


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


class IngestEngine:
    def __init__(
        self,
        warehouse: Warehouse,
        *,
        clients: dict[Provider, Any] | None = None,
        gate: StalenessGate | None = None,
    ) -> None:
        self.warehouse = warehouse
        self.clients = clients or {}
        self.gate = gate or StalenessGate(warehouse)

    def _client(self, provider: Provider) -> Any:
        if provider not in self.clients:
            self.clients[provider] = _PROVIDER_CLIENTS[provider]()
        return self.clients[provider]

    def _call(self, spec: EndpointSpec, kwargs: dict[str, Any]) -> Any:
        method = getattr(self._client(spec.provider), spec.method or "")
        if spec.method is None:
            raise ValueError(f"{spec.name}: DERIVED endpoints cannot be called via the API")
        return method(**kwargs)

    def _call_kwargs(self, spec: EndpointSpec, dimension_key: str, now: datetime, watermark: Any) -> dict[str, Any]:
        """kwargs for the client method, derived from spec + dimension + state.

        dimension_key is "AAPL" for ticker-scoped endpoints, or the full grain
        "AAPL|4|2025" where a request targets one quarter/year (transcript).
        """
        sym = dimension_key.split("|")[0]
        by_name: dict[str, dict[str, Any]] = {
            "quote": {"symbol": sym},
            "company_profile2": {"symbol": sym},
            "basic_financials": {"symbol": sym, "metric": "all"},
            "financials_reported": {"symbol": sym, "freq": "annual"},
            "eps_surprises": {"symbol": sym},
            "recommendation_trends": {"symbol": sym},
            "peers": {"symbol": sym},
            "insider_sentiment": {
                "symbol": sym,
                "from_date": f"{now.year}-01-01",
                "to_date": now.date().isoformat(),
            },
            "market_news": {"limit": 1000, "sort": "LATEST"},
        }
        if spec.name == "earnings_call_transcript":
            parts = dimension_key.split("|")
            if len(parts) < 3:
                raise ValueError("earnings_call_transcript: dimension must be SYM|Q|YYYY")
            return {"symbol": parts[0], "quarter": f"{parts[2]}Q{parts[1]}"}
        if spec.name == "prices.daily":
            kwargs: dict[str, Any] = {"symbol": sym}
            if watermark is not None and watermark.high_watermark:
                kwargs["start_date"] = watermark.high_watermark  # incremental since last fetch
            return kwargs
        if spec.name not in by_name:
            raise ValueError(f"{spec.name}: no on-demand call signature (use ingest_scheduled)")
        return by_name[spec.name]

    def _scheduled_kwargs(self, spec: EndpointSpec, now: datetime, params: dict[str, Any] | None) -> dict[str, Any]:
        params = dict(params or {})
        if spec.name in ("ipo_calendar", "earnings_calendar"):
            if "from_date" not in params or "to_date" not in params:
                # IPO calendar: backfill the trailing week too, so "recently
                # priced" listings stay visible to the frontend (it filters
                # `date >= current_date - 7`).
                params.setdefault(
                    "from_date",
                    (now.date() - timedelta(days=7)).isoformat()
                    if spec.name == "ipo_calendar"
                    else now.date().isoformat(),
                )
                params.setdefault("to_date", (now.date() + timedelta(days=_SCHEDULED_DEFAULT_WINDOW_DAYS)).isoformat())
            return params
        return params

    def _land_rows(
        self,
        rows: dict[str, list[dict[str, Any]]],
        now: datetime,
        high_watermark: str | None = None,
    ) -> int:
        written = 0
        for artifact, artifact_rows in rows.items():
            if not artifact_rows:
                continue
            written += self.warehouse.land(artifact, artifact_rows, fetched_at=now, high_watermark=high_watermark)
        return written

    def _ingest(self, spec: EndpointSpec, dimension_key: str, kwargs: dict[str, Any], now: datetime) -> IngestResult:
        payload = self._call(spec, kwargs)
        rows = normalize_for(spec.name, payload, dimension_key, now)
        high_watermark = (
            max(r["date"].isoformat() for r in rows["raw_prices_daily"]) if spec.name == "prices.daily" else None
        )
        written = self._land_rows(rows, now, high_watermark)
        return IngestResult(spec.name, dimension_key, True, "fetch complete", written, high_watermark)

    def ingest_on_demand(
        self,
        endpoint_name: str,
        dimension_key: str,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> IngestResult:
        spec = get_endpoint(endpoint_name)
        now_dt = _utc(now)

        if not force:
            decision = self.gate.should_fetch(spec.name, dimension_key, now=now_dt)
            if not decision.should_fetch:
                return IngestResult(spec.name, dimension_key, False, decision.reason, 0)

        watermark = self.warehouse.get_watermark(f"raw.{spec.artifacts[0]}", dimension_key)
        kwargs = self._call_kwargs(spec, dimension_key, now_dt, watermark)
        return self._ingest(spec, dimension_key, kwargs, now_dt)

    def ingest_scheduled(
        self,
        endpoint_name: str,
        *,
        params: dict[str, Any] | None = None,
        dimension_key: str | None = None,
        now: datetime | None = None,
    ) -> IngestResult:
        spec = get_endpoint(endpoint_name)
        now_dt = _utc(now)
        kwargs = self._scheduled_kwargs(spec, now_dt, params)
        return self._ingest(spec, dimension_key or spec.name, kwargs, now_dt)