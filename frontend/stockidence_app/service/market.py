from __future__ import annotations

"""Market-wide indicators for the main page and Discover.

Reads the pipeline warehouse (raw layer, which doubles as the staleness-aware
cache); falls back to deterministic demo data per-section when the warehouse
has nothing, so the UI never hard-fails during build-out. Every getter is
self-contained: one bad section degrades to demo, never to a page error.
"""

import os
from datetime import datetime, timezone

_PATH = None


def _db_path() -> str:
    global _PATH
    if _PATH is None:
        _PATH = os.environ.get(
            "STOCKIDENCE_DB",
            str(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "stockidence.duckdb")),
        )
    return _PATH


def _read(sql: str, params: list | None = None) -> list[tuple] | None:
    """Run a read query against the warehouse; None on any failure."""
    try:
        import duckdb
    except ImportError:
        return None
    try:
        con = duckdb.connect(_db_path(), read_only=True)
        rows = con.execute(sql, params or []).fetchall()
        con.close()
        return rows
    except Exception:
        return None


def _latest_macro_series(indicator: str, points: int = 8) -> list[dict]:
    rows = _read(
        """
        SELECT json_extract_string(payload, '$.date'), json_extract_string(payload, '$.value')
        FROM raw.raw_macro_indicators
        WHERE indicator = ?
        ORDER BY date DESC LIMIT ?
        """,
        [indicator, points],
    )
    if not rows:
        return []
    return [{"date": d, "value": _num(v)} for d, v in reversed(rows) if v]


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_quote(ticker: str) -> dict | None:
    """Latest Finnhub quote for a ticker from the raw cache (TTL ~1 min).

    Returns None when the warehouse is absent or the ticker has no quote row.
    The raw key is the ticker only, so every landing replaces the previous
    quote — no history is kept in the raw layer.
    """
    rows = _read(
        """
        SELECT json_extract_string(payload, '$.c'),
               json_extract_string(payload, '$.h'),
               json_extract_string(payload, '$.l'),
               json_extract_string(payload, '$.o'),
               json_extract_string(payload, '$.pc'),
               json_extract_string(payload, '$.t')
        FROM raw.raw_quotes
        WHERE ticker = ?
        """,
        [ticker.upper()],
    )
    if not rows or not rows[0][0]:
        return None
    c, h, l, o, pc, t = rows[0]
    ts = None
    if t:
        try:
            ts = datetime.fromtimestamp(int(t), tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            ts = None
    return {
        "price": _num(c),
        "high": _num(h),
        "low": _num(l),
        "open": _num(o),
        "prev_close": _num(pc),
        "as_of": ts,
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_news_time(raw: str) -> str:
    """Alpha Vantage / Finnhub timestamp 'YYYYMMDDTHHMMSS' -> readable."""
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S")
        return dt.strftime("%b %d, %H:%M")
    except (TypeError, ValueError):
        return raw


_MACRO_DEFS = [
    ("inflation", "Inflation", "%", "YoY annual rate"),
    ("cpi", "CPI", "index", "Consumer price index"),
    ("unemployment", "Unemployment Rate", "%", "Seasonally adjusted"),
    ("federal_funds_rate", "Federal Funds Rate", "%", "Effective rate"),
    ("real_gdp_per_capita", "Real GDP per Capita", "$", "Quarterly, USD"),
    ("natural_gas", "Natural Gas", "$/MMBtu", "Henry Hub spot price"),
]


def _month_add(ym: str, months: int) -> str:
    """Shift a 'YYYY-MM' string by N months."""
    year, month = int(ym[:4]), int(ym[5:7])
    idx = year * 12 + (month - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _inflation_from_cpi(points: int = 8) -> list[dict]:
    """YoY inflation derived from the CPI monthly series we already ingest.

    AV's INFLATION endpoint is an annual series that froze upstream at Jan
    2024; CPI keeps updating monthly, so YoY = cpi_t / cpi_t-12 - 1 gives a
    current 'Inflation' card without another API dependency.
    """
    rows = _latest_macro_series("cpi", points=points + 12)
    by_month = {r["date"][:7]: r["value"] for r in rows}
    out: list[dict] = []
    for r in rows:
        base = by_month.get(_month_add(r["date"][:7], -12))
        if r["value"] is None or not base:
            continue
        out.append({"date": r["date"], "value": round((r["value"] / base - 1.0) * 100.0, 2)})
    return out[-points:]


def _series_stale(series: list[dict], reference: list[dict], months: int = 6) -> bool:
    """True when `reference` runs >N months ahead of `series` (or series empty)."""
    if not series:
        return True
    if not reference:
        return False
    return _month_add(series[-1]["date"][:7], months) < reference[-1]["date"][:7]


def get_macro_metrics() -> list[dict]:
    """Latest quarterly/monthly macro indicators (inflation, CPI, etc.)."""
    rows = _read(
        """
        SELECT indicator, min(date), max(date)
        FROM raw.raw_macro_indicators GROUP BY 1
        """
    )
    live = {r[0]: r for r in rows} if rows else {}
    cpi_series = _latest_macro_series("cpi", points=8)
    out: list[dict] = []
    for indicator, label, unit, detail in _MACRO_DEFS:
        series = _latest_macro_series(indicator, points=8)
        if indicator == "inflation" and _series_stale(series, cpi_series):
            derived = _inflation_from_cpi()
            if derived:
                series, detail = derived, "Derived from CPI YoY"
        latest = series[-1] if series else None
        if latest is None or indicator not in live:
            continue  # untouched indicator: let the demo fill the grid
        value = latest["value"]
        if indicator == "real_gdp_per_capita":
            value = round(value) if value is not None else None
        else:
            value = round(value, 2) if value is not None else None
        out.append({"label": label, "value": value, "unit": unit, "detail": detail,
                    "as_of": latest["date"], "series": series})
    if out:
        return out
    return _DEMO_MACRO


def get_commodities() -> list[dict]:
    """Spot prices for gold and silver, in USD, from the raw cache."""
    rows = _read(
        """
        SELECT nominal,
               json_extract_string(payload, '$.date'),
               COALESCE(json_extract_string(payload, '$.price'),
                        json_extract_string(payload, '$.value'))
        FROM (SELECT nominal, payload, ROW_NUMBER() OVER (PARTITION BY nominal ORDER BY date DESC) rn
              FROM raw.raw_commodities) WHERE rn = 1
        """
    )
    if not rows:
        return _DEMO_COMMODITIES
    out = []
    for nominal, date, price in rows:
        price = _num(price)
        out.append({
            "label": "Gold" if nominal == "GOLD" else "Silver",
            "nominal": nominal,
            "price": round(price, 2) if price is not None else None,
            "unit": "USD/oz",
            "timestamp": date,
        })
    return out


def get_market_movers() -> dict:
    """Top gainers, losers, and most actively traded, bucket-aggregated."""
    rows = _read(
        """
        SELECT ticker,
               json_extract_string(payload, '$.bucket'),
               json_extract_string(payload, '$.price'),
               json_extract_string(payload, '$.change_amount'),
               json_extract_string(payload, '$.change_percentage'),
               json_extract_string(payload, '$.volume')
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker, json_extract_string(payload, '$.bucket') ORDER BY date DESC) rn
            FROM raw.raw_gainers_losers)
        WHERE rn = 1
        """
    )
    if not rows:
        return {
            "metadata": "Top gainers, losers, and most actively traded US tickers (demo)",
            "last_updated": _now() + " US/Eastern",
            "top_gainers": _decorate(_DEMO_MOVERS["top_gainers"]),
            "top_losers": _decorate(_DEMO_MOVERS["top_losers"]),
            "most_actively_traded": _decorate(_DEMO_MOVERS["most_actively_traded"]),
        }
    movers: dict[str, list[dict]] = {"top_gainers": [], "top_losers": [], "most_actively_traded": []}
    for ticker, bucket, price, change_amount, change_percentage, volume in rows:
        if bucket in movers and price is not None:
            movers[bucket].append({
                "ticker": ticker, "price": price, "change_amount": change_amount,
                "change_percentage": change_percentage, "volume": volume,
            })
    return {
        "metadata": "Top gainers, losers, and most actively traded US tickers",
        "last_updated": _now() + " US/Eastern",
        "top_gainers": _decorate(movers["top_gainers"]),
        "top_losers": _decorate(movers["top_losers"]),
        "most_actively_traded": _decorate(movers["most_actively_traded"]),
    }


def _decorate(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        signed = str(row["change_percentage"]).rstrip("%").replace("−", "-")
        volume = row.get("volume")
        amount = _num(row["change_amount"])
        pct = _num(signed)
        out.append({
            **row,
            "is_gain": signed != "" and "-" not in signed,
            "volume_display": f"{int(float(volume)):,}" if volume else None,
            "change_display": (
                f"{amount:+.2f} ({pct:+.2f}%)"
                if amount is not None and pct is not None
                else f"{row['change_amount']} ({row['change_percentage']})"
            ),
        })
    return out


def get_ipo_calendar(limit: int = 10) -> list[dict]:
    """Upcoming and recently priced IPOs on US exchanges (up to `limit` rows)."""
    rows = _read(
        """
        SELECT payload FROM raw.raw_ipo_calendar
        WHERE date >= current_date - INTERVAL 7 DAY
        ORDER BY date ASC LIMIT ?
        """,
        [limit],
    )
    if not rows:
        return _DEMO_IPO
    import json
    out = []
    for (payload,) in rows:
        p = json.loads(payload) if isinstance(payload, str) else payload
        if p is None or not isinstance(p, dict):
            continue
        out.append({
            "date": p.get("date"),
            "exchange": p.get("exchange"),
            "name": p.get("name"),
            "numberOfShares": _fmt_int(p.get("numberOfShares")),
            "price": p.get("price") or None,
            "status": p.get("status"),
            "symbol": p.get("symbol"),
            "totalSharesValue": _fmt_int(p.get("totalSharesValue")),
        })
    return out if out else _DEMO_IPO


def _fmt_int(v) -> str | None:
    if v is None:
        return None
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v) if v else None


def get_earnings_calendar(limit: int = 10) -> list[dict]:
    """Upcoming earnings releases with consensus estimates (up to `limit` rows)."""
    rows = _read(
        """
        SELECT payload FROM raw.raw_earnings_calendar
        WHERE CAST(json_extract_string(payload, '$.date') AS DATE) >= current_date
        ORDER BY json_extract_string(payload, '$.date') ASC LIMIT ?
        """,
        [limit],
    )
    if not rows:
        return _DEMO_EARNINGS
    import json
    out = []
    for (payload,) in rows:
        p = json.loads(payload) if isinstance(payload, str) else payload
        if p is None or not isinstance(p, dict):
            continue
        out.append({
            "date": p.get("date"),
            "symbol": p.get("symbol"),
            "quarter": p.get("quarter"),
            "year": p.get("year"),
            "hour": p.get("hour"),
            "eps_estimate": _num(p.get("epsEstimate")),
            "eps_actual": _num(p.get("epsActual")),
            "eps_actual_display": f"${p['epsActual']:.2f}" if p.get("epsActual") is not None else None,
            "revenue_estimate": _num(p.get("revenueEstimate")),
            "revenue_estimate_display": _fmt_money(p.get("revenueEstimate")),
            "revenue_actual": _num(p.get("revenueActual")),
            "revenue_actual_display": _fmt_money(p.get("revenueActual")),
        })
    return out if out else _DEMO_EARNINGS


def _fmt_money(v) -> str | None:
    if v is None:
        return None
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return None


def get_market_news() -> list[dict]:
    """Market-wide news items with sentiment labels.

    Capped at 1000 — the daily pipeline fetch size — so on-demand paging in
    the UI has a real window to move through without re-hitting the API.
    """
    rows = _read(
        """
        SELECT payload FROM raw.raw_news_articles
        ORDER BY (payload->>'time_published') DESC LIMIT 1000
        """
    )
    if not rows:
        return [_finalize_news(item) for item in _DEMO_NEWS]
    import json
    out = []
    for (payload,) in rows:
        p = json.loads(payload) if isinstance(payload, str) else payload
        if p is None or not isinstance(p, dict):
            continue
        tickers = p.get("ticker_sentiment", [])
        out.append({
            "title": p.get("title"),
            "url": p.get("url"),
            "time_published": _format_news_time(p.get("time_published")),
            "authors": _str_list(p.get("authors")),
            "summary": p.get("summary"),
            "source": p.get("source"),
            "overall_sentiment_score": _num(p.get("overall_sentiment_score")),
            "overall_sentiment_label": p.get("overall_sentiment_label"),
            "sentiment_tickers": ", ".join(t.get("ticker") for t in tickers if t.get("ticker")) if tickers else "",
        })
    return out if out else [_finalize_news(item) for item in _DEMO_NEWS]


def _finalize_news(item: dict) -> dict:
    return {**item, "time_published": _format_news_time(item["time_published"])}


def _str_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if v:
        return [str(v)]
    return []


# --- deterministic demo placeholders (kept in sync with API.md schemas) ---

_DEMO_MACRO = [
    {"label": "Inflation", "value": 2.95, "unit": "%", "detail": "YoY annual rate", "as_of": "2026-07-01",
     "series": [{"date": "2024-01-01", "value": 2.95}, {"date": "2025-01-01", "value": 3.41}, {"date": "2026-01-01", "value": 2.85}, {"date": "2026-07-01", "value": 2.62}]},
    {"label": "CPI", "value": 333.918, "unit": "index", "detail": "Consumer price index", "as_of": "2026-07-01",
     "series": [{"date": "2025-01-01", "value": 318.2}, {"date": "2026-01-01", "value": 329.1}, {"date": "2026-07-01", "value": 333.9}]},
    {"label": "Unemployment Rate", "value": 4.1, "unit": "%", "detail": "Seasonally adjusted", "as_of": "2026-07-01",
     "series": [{"date": "2025-07-01", "value": 4.3}, {"date": "2026-01-01", "value": 4.2}, {"date": "2026-07-01", "value": 4.1}]},
    {"label": "Federal Funds Rate", "value": 3.63, "unit": "%", "detail": "Effective rate", "as_of": "2026-07-01",
     "series": [{"date": "2025-01-01", "value": 4.33}, {"date": "2026-01-01", "value": 3.84}, {"date": "2026-07-01", "value": 3.63}]},
    {"label": "Real GDP per Capita", "value": 88698, "unit": "$", "detail": "Quarterly, USD", "as_of": "2026-06-30",
     "series": [{"date": "2025-06-30", "value": 86410}, {"date": "2026-06-30", "value": 88698}]},
    {"label": "Natural Gas", "value": 2.89, "unit": "$/MMBtu", "detail": "Henry Hub spot price", "as_of": "2026-07-01",
     "series": [{"date": "2025-11-01", "value": 3.28}, {"date": "2026-03-01", "value": 2.54}, {"date": "2026-07-01", "value": 2.89}]},
]

_DEMO_COMMODITIES = [
    {"label": "Gold", "nominal": "GOLD", "price": 3448.12, "unit": "USD/oz", "timestamp": _now()},
    {"label": "Silver", "nominal": "SILVER", "price": 64.69, "unit": "USD/oz", "timestamp": _now()},
]

_DEMO_MOVERS = {
    "top_gainers": [
        {"ticker": "WETO", "price": "8.22", "change_amount": "4.61", "change_percentage": "127.70%", "volume": "58226265"},
        {"ticker": "MYSEW", "price": "0.003", "change_amount": "0.0014", "change_percentage": "87.50%", "volume": "45772"},
    ],
    "top_losers": [
        {"ticker": "NVO.E", "price": "0.05", "change_amount": "-3.50", "change_percentage": "-41.18%", "volume": "120000"},
        {"ticker": "ABCD", "price": "0.42", "change_amount": "-0.28", "change_percentage": "-40.00%", "volume": "803112"},
    ],
    "most_actively_traded": [
        {"ticker": "NVDA", "price": "152.44", "change_amount": "2.88", "change_percentage": "1.93%", "volume": "182342345"},
        {"ticker": "AAPL", "price": "232.50", "change_amount": "-1.16", "change_percentage": "-0.50%", "volume": "81234567"},
    ],
}

_DEMO_IPO = [
    {"date": "2026-08-20", "exchange": "NASDAQ", "name": "NovaGrid Energy", "numberOfShares": "15,000,000",
     "price": "18.00 - 20.00", "status": "expected", "symbol": "NGRE", "totalSharesValue": "285,000,000"},
    {"date": "2026-08-21", "exchange": "NYSE", "name": "Cobalt Cloud Systems", "numberOfShares": "12,000,000",
     "price": "24.00 - 28.00", "status": "expected", "symbol": "CCLD", "totalSharesValue": "312,000,000"},
]

_DEMO_EARNINGS = [
    {"date": "2026-08-20", "symbol": "AAPL", "quarter": 3, "year": 2026, "hour": "amc",
     "eps_estimate": 2.53, "eps_actual": None, "revenue_estimate": 104200000000, "revenue_actual": None},
    {"date": "2026-08-25", "symbol": "COST", "quarter": 4, "year": 2026, "hour": "bmo",
     "eps_estimate": 5.31, "eps_actual": None, "revenue_estimate": 62000000000, "revenue_actual": None},
]

_DEMO_NEWS = [
    {"title": "NVIDIA climbs as data-center demand stays ahead of supply",
     "url": "https://example.com/nvidia", "time_published": "20260814T121500",
     "authors": ["Market Wire"], "summary": "NVIDIA's data-center segment continues to outpace supply.",
     "source": "Market Wire", "overall_sentiment_score": 0.42,
     "overall_sentiment_label": "Bullish", "sentiment_tickers": "NVDA, AMD"},
    {"title": "Treasury yields slip after cooler CPI print",
     "url": "https://example.com/cpi", "time_published": "20260813T141000",
     "authors": ["Fixed Income Desk"], "summary": "The 10-year yield fell after the CPI report came in below consensus.",
     "source": "Fixed Income Desk", "overall_sentiment_score": 0.31,
     "overall_sentiment_label": "Somewhat-Bullish", "sentiment_tickers": ""},
]