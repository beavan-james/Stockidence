from __future__ import annotations

"""Demo market data for the main-page indicators and Discover page.

Mirrors the endpoint schemas recorded in API.md (macro indicators,
commodities, top gainers/losers, IPO & earnings calendars, market news).
No live API client or pipeline exists yet, so these are deterministic
placeholders that keep the UI functional — swap the function bodies for
warehouse mart reads once those endpoints are ingested.
"""

from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_news_time(raw: str) -> str:
    """Finnhub timestamp 'YYYYMMDDTHHMMSS' -> readable 'Aug 14, 04:49'."""
    try:
        dt = datetime.strptime(raw, "%Y%m%dT%H%M%S")
        return dt.strftime("%b %d, %H:%M")
    except ValueError:
        return raw


def get_macro_metrics() -> list[dict]:
    """Latest quarterly/monthly macro indicators (inflation, CPI, etc.)."""
    return [
        {
            "label": "Inflation",
            "value": 2.95,
            "unit": "%",
            "detail": "YoY annual rate",
            "as_of": "2024-01-01",
            "series": [
                {"date": "2024-01-01", "value": 2.95},
                {"date": "2024-07-01", "value": 3.22},
                {"date": "2025-01-01", "value": 3.41},
                {"date": "2025-07-01", "value": 3.18},
                {"date": "2026-01-01", "value": 2.85},
                {"date": "2026-07-01", "value": 2.62},
            ],
        },
        {
            "label": "CPI",
            "value": 333.918,
            "unit": "index",
            "detail": "Consumer price index",
            "as_of": "2026-07-01",
            "series": [
                {"date": "2024-07-01", "value": 315.0},
                {"date": "2025-01-01", "value": 318.2},
                {"date": "2025-07-01", "value": 324.5},
                {"date": "2026-01-01", "value": 329.1},
                {"date": "2026-07-01", "value": 333.9},
            ],
        },
        {
            "label": "Unemployment Rate",
            "value": 4.1,
            "unit": "%",
            "detail": "Seasonally adjusted",
            "as_of": "2026-07-01",
            "series": [
                {"date": "2024-07-01", "value": 4.0},
                {"date": "2025-01-01", "value": 3.9},
                {"date": "2025-07-01", "value": 4.3},
                {"date": "2026-01-01", "value": 4.2},
                {"date": "2026-07-01", "value": 4.1},
            ],
        },
        {
            "label": "Federal Funds Rate",
            "value": 3.63,
            "unit": "%",
            "detail": "Effective rate",
            "as_of": "2026-07-01",
            "series": [
                {"date": "2024-07-01", "value": 5.33},
                {"date": "2025-01-01", "value": 4.33},
                {"date": "2025-07-01", "value": 4.08},
                {"date": "2026-01-01", "value": 3.84},
                {"date": "2026-07-01", "value": 3.63},
            ],
        },
        {
            "label": "Real GDP per Capita",
            "value": 88698,
            "unit": "$",
            "detail": "Quarterly, USD",
            "as_of": "2026-06-30",
            "series": [
                {"date": "2024-06-30", "value": 84320},
                {"date": "2024-12-31", "value": 85210},
                {"date": "2025-06-30", "value": 86410},
                {"date": "2025-12-31", "value": 87450},
                {"date": "2026-06-30", "value": 88698},
            ],
        },
        {
            "label": "Natural Gas",
            "value": 2.89,
            "unit": "$/MMBtu",
            "detail": "Henry Hub spot price",
            "as_of": "2026-07-01",
            "series": [
                {"date": "2025-02-01", "value": 3.95},
                {"date": "2025-08-01", "value": 2.41},
                {"date": "2025-11-01", "value": 3.28},
                {"date": "2026-03-01", "value": 2.54},
                {"date": "2026-07-01", "value": 2.89},
            ],
        },
    ]


def get_commodities() -> list[dict]:
    """Spot prices for gold and silver, in USD."""
    return [
        {
            "label": "Gold",
            "nominal": "GOLD",
            "price": 3448.12,
            "unit": "USD/oz",
            "timestamp": _now(),
        },
        {
            "label": "Silver",
            "nominal": "SILVER",
            "price": 64.69,
            "unit": "USD/oz",
            "timestamp": _now(),
        },
    ]


def get_market_movers() -> dict:
    """Top gainers, losers, and most actively traded US tickers."""
    movers = {
        "top_gainers": [
            {"ticker": "WETO", "price": "8.22", "change_amount": "4.61", "change_percentage": "127.70%", "volume": "58226265"},
            {"ticker": "MYSEW", "price": "0.003", "change_amount": "0.0014", "change_percentage": "87.50%", "volume": "45772"},
            {"ticker": "AACBR", "price": "0.0125", "change_amount": "0.0118", "change_percentage": "1685.71%", "volume": "4181248"},
        ],
        "top_losers": [
            {"ticker": "NVO.E", "price": "0.05", "change_amount": "-3.50", "change_percentage": "-41.18%", "volume": "120000"},
            {"ticker": "ABCD", "price": "0.42", "change_amount": "-0.28", "change_percentage": "-40.00%", "volume": "803112"},
            {"ticker": "BRSH", "price": "2.10", "change_amount": "-1.05", "change_percentage": "-33.33%", "volume": "244000"},
        ],
        "most_actively_traded": [
            {"ticker": "NVDA", "price": "152.44", "change_amount": "2.88", "change_percentage": "1.93%", "volume": "182342345"},
            {"ticker": "AAPL", "price": "232.50", "change_amount": "-1.16", "change_percentage": "-0.50%", "volume": "81234567"},
            {"ticker": "TSLA", "price": "348.02", "change_amount": "9.14", "change_percentage": "2.70%", "volume": "74321098"},
        ],
    }

    def _decorate(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            signed = row["change_percentage"].rstrip("%").replace("−", "-")
            out.append(
                {
                    **row,
                    "is_gain": "-" not in signed,
                    "volume_display": f"{int(float(row['volume'])):,}",
                    "change_display": f"{row['change_amount']} ({row['change_percentage']})",
                }
            )
        return out

    return {
        "metadata": "Top gainers, losers, and most actively traded US tickers",
        "last_updated": _now() + " US/Eastern",
        "top_gainers": _decorate(movers["top_gainers"]),
        "top_losers": _decorate(movers["top_losers"]),
        "most_actively_traded": _decorate(movers["most_actively_traded"]),
    }


def get_ipo_calendar() -> list[dict]:
    """Upcoming and recently priced IPOs on US exchanges."""
    return [
        {
            "date": "2026-08-20",
            "exchange": "NASDAQ",
            "name": "NovaGrid Energy",
            "numberOfShares": "15000000",
            "price": "18.00 - 20.00",
            "status": "expected",
            "symbol": "NGRE",
            "totalSharesValue": "285000000",
        },
        {
            "date": "2026-08-21",
            "exchange": "NYSE",
            "name": "Cobalt Cloud Systems",
            "numberOfShares": "12000000",
            "price": "24.00 - 28.00",
            "status": "expected",
            "symbol": "CCLD",
            "totalSharesValue": "312000000",
        },
        {
            "date": "2026-08-14",
            "exchange": "NASDAQ",
            "name": "Brightpath Biotech",
            "numberOfShares": "8000000",
            "price": "15.00",
            "status": "priced",
            "symbol": "BRPH",
            "totalSharesValue": "120000000",
        },
        {
            "date": "2026-08-10",
            "exchange": "NYSE",
            "name": "Atlas Freight Partners",
            "numberOfShares": "20000000",
            "price": "12.00 - 14.00",
            "status": "withdrawn",
            "symbol": "ATLF",
            "totalSharesValue": "260000000",
        },
        {
            "date": "2026-08-07",
            "exchange": "NASDAQ",
            "name": "Helio Rocket Systems",
            "numberOfShares": "22500000",
            "price": "10.00",
            "status": "priced",
            "symbol": "HRKT",
            "totalSharesValue": "225000000",
        },
        {
            "date": "2026-08-27",
            "exchange": "NASDAQ",
            "name": "Pulse Bio Labs",
            "numberOfShares": "9000000",
            "price": "30.00 - 34.00",
            "status": "filed",
            "symbol": "PULB",
            "totalSharesValue": "288000000",
        },
    ]


def get_earnings_calendar() -> list[dict]:
    """Upcoming earnings releases with consensus estimates."""
    def _fmt_money(v):
        if v is None:
            return None
        return f"{v:,.0f}"

    def _fmt_eps(v):
        return f"{v:.2f}" if v is not None else None

    return [
        {
            "date": "2026-08-18",
            "symbol": "NVDA",
            "quarter": 2,
            "year": 2026,
            "hour": "amc",
            "eps_estimate": 1.42,
            "eps_actual": None,
            "eps_actual_display": None,
            "revenue_estimate": 38400000000,
            "revenue_estimate_display": "$38,400,000,000",
            "revenue_actual": None,
        },
        {
            "date": "2026-08-20",
            "symbol": "AAPL",
            "quarter": 3,
            "year": 2026,
            "hour": "amc",
            "eps_estimate": 2.53,
            "eps_actual": None,
            "eps_actual_display": None,
            "revenue_estimate": 104200000000,
            "revenue_estimate_display": "$104,200,000,000",
            "revenue_actual": None,
        },
        {
            "date": "2026-08-25",
            "symbol": "COST",
            "quarter": 4,
            "year": 2026,
            "hour": "bmo",
            "eps_estimate": 5.31,
            "eps_actual": None,
            "eps_actual_display": None,
            "revenue_estimate": 62000000000,
            "revenue_estimate_display": "$62,000,000,000",
            "revenue_actual": None,
        },
        {
            "date": "2026-08-14",
            "symbol": "WMT",
            "quarter": 2,
            "year": 2026,
            "hour": "bmo",
            "eps_actual": 0.68,
            "eps_actual_display": "$0.68",
            "eps_estimate": 0.62,
            "revenue_actual": 174300000000,
            "revenue_actual_display": "$174,300,000,000",
            "revenue_estimate": 171200000000,
            "revenue_estimate_display": "$171,200,000,000",
        },
        {
            "date": "2026-08-13",
            "symbol": "TSLA",
            "quarter": 3,
            "year": 2026,
            "hour": "amc",
            "eps_actual": 0.92,
            "eps_actual_display": "$0.92",
            "eps_estimate": 0.85,
            "revenue_actual": 29200000000,
            "revenue_actual_display": "$29,200,000,000",
            "revenue_estimate": 28700000000,
            "revenue_estimate_display": "$28,700,000,000",
        },
    ]


def get_market_news() -> list[dict]:
    """Market-wide news items with sentiment labels."""
    items = [
        {
            "title": "STATE STREET CORP Adds to Allegion PLC (ALLE) Stake -- Shares Look Fairly Valued on GF Value",
            "url": "https://www.gurufocus.com/news/9033452/state-street-corp-adds-to-allegion-plc-alle-stake-shares-look-fairly-valued-on-gf-value",
            "time_published": "20260814T004908",
            "authors": ["GuruFocus News"],
            "summary": "STATE STREET CORP increased its stake in Allegion PLC (ALLE) by 77,816 shares on June 30, 2026, investing approximately $10.93 million.",
            "source": "GuruFocus",
            "overall_sentiment_score": 0.177738,
            "overall_sentiment_label": "Somewhat-Bullish",
            "sentiment_tickers": "ALLE, STT",
        },
        {
            "title": "NVIDIA climbs as data-center demand stays ahead of supply",
            "url": "https://example.com/nvidia-data-center-demand",
            "time_published": "20260814T121500",
            "authors": ["Market Wire"],
            "summary": "NVIDIA's data-center segment continues to outpace supply, with hyperscaler orders pushing backlog at record levels heading into fiscal Q2 results.",
            "source": "Market Wire",
            "overall_sentiment_score": 0.42,
            "overall_sentiment_label": "Bullish",
            "sentiment_tickers": "NVDA, AMD",
        },
        {
            "title": "Treasury yields slip after cooler CPI print",
            "url": "https://example.com/treasury-yields-cpi",
            "time_published": "20260813T141000",
            "authors": ["Fixed Income Desk"],
            "summary": "The 10-year yield fell after the CPI report came in below consensus, firming expectations that the Fed will ease policy again in September.",
            "source": "Fixed Income Desk",
            "overall_sentiment_score": 0.31,
            "overall_sentiment_label": "Somewhat-Bullish",
            "sentiment_tickers": "",
        },
        {
            "title": "Crude oil slides on demand concerns; airlines note cheaper fuel tailwind",
            "url": "https://example.com/crude-demand-concerns",
            "time_published": "20260812T093000",
            "authors": ["Energy Now"],
            "summary": "Brent crude slipped below $68 as demand forecasts were trimmed. U.S. carriers flagged cheaper jet fuel as a margin tailwind for Q3.",
            "source": "Energy Now",
            "overall_sentiment_score": -0.18,
            "overall_sentiment_label": "Somewhat-Bearish",
            "sentiment_tickers": "DAL, XOM",
        },
    ]
    for item in items:
        item["time_published"] = _format_news_time(item["time_published"])
    return items