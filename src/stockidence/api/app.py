from __future__ import annotations

"""FastAPI application serving the mart layer to the React SPA.

Every route is a one-liner over stockidence.service — this module owns
HTTP concerns only: routing, validation, error mapping, and CORS for the
Vite dev server. Run locally with:

    uv run uvicorn stockidence.api.app:app --reload
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import market_router, meta_router, rating_router

_DEFAULT_ORIGINS = "http://localhost:5173"


def _allowed_origins() -> list[str]:
    raw = os.environ.get("STOCKIDENCE_CORS_ORIGINS", _DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stockidence API",
        description="Confidence ratings and market context from the pipeline warehouse.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(rating_router)
    app.include_router(market_router)
    app.include_router(meta_router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
