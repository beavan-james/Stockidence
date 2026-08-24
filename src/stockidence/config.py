"""Configuration for the pipeline.

API keys are read from the environment / a local .env file — never hardcoded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the pipeline."""

    finnhub_api_key: str
    twelve_data_api_key: str
    alpha_vantage_api_key: str
    min_interval_seconds: dict[str, float] = None
    alpha_vantage_pace_file: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env()
        return cls(
            finnhub_api_key=os.environ.get("FINNHUB_API_KEY", "")
            or os.environ.get("X_FINNHUB_API_KEY", ""),
            twelve_data_api_key=os.environ.get("TWELVE_DATA_API_KEY", ""),
            alpha_vantage_api_key=os.environ.get("ALPHA_VANTAGE_API_KEY", ""),
            alpha_vantage_pace_file=os.environ.get(
                "ALPHA_VANTAGE_PACE_FILE",
                str(Path.home() / ".stockidence" / "av_pace"),
            ),
            min_interval_seconds={
                "finnhub": float(os.environ.get("FINNHUB_MIN_INTERVAL_S", "1.05")),
                "twelve_data": float(os.environ.get("TWELVE_DATA_MIN_INTERVAL_S", "8.0")),
                "alpha_vantage": float(os.environ.get("ALPHA_VANTAGE_MIN_INTERVAL_S", "61.0")),
            },
        )


def load_settings() -> Settings:
    return Settings.from_env()