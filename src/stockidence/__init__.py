"""Stockidence pipeline package.

Data intake clients, endpoint metadata, and (later) Dagster assets.
"""

from .ingest.clients.alpha_vantage import AlphaVantageClient
from .ingest.clients.finnhub import FinnhubClient
from .ingest.clients.twelve_data import TwelveDataClient
from .config import Settings, load_settings
from .ingest.endpoints import REGISTRY, EndpointSpec

__all__ = [
    "AlphaVantageClient",
    "EndpointSpec",
    "FinnhubClient",
    "REGISTRY",
    "Settings",
    "TwelveDataClient",
    "load_settings",
]