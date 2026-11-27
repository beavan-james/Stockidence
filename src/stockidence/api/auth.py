"""Admin guard for the routes that launch pipeline runs.

The site only reads. A ticker page starts its own refresh through
GET /api/rating/{ticker}, which checks the ticker against the symbol list
and waits out a per-ticker cooldown. The POST routes take any list of
tickers, so left open they would let anyone spend the free-tier quotas
(one request of 800 tickers is Twelve Data's whole day) or add tickers that
every Friday and quarterly refresh then pays for. They need an X-Admin-Token
header matching STOCKIDENCE_ADMIN_TOKEN, and stay shut while that's unset.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from ..config import load_settings

ADMIN_HEADER = "X-Admin-Token"


def configured_token() -> str:
    return load_settings().admin_token


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = configured_token()
    if not expected:
        raise HTTPException(
            status_code=403, detail="admin routes are off: STOCKIDENCE_ADMIN_TOKEN is not set"
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail=f"missing or wrong {ADMIN_HEADER} header")
