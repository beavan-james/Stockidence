"""Staging rebuild: raw → typed, cleaned, deduped bars (staging layer).

Staging cleans, mart aggregates. stg_prices_daily is typing/cleaning/dedup
plus grain-preserving transforms (return_1d); stg_fred_market types the FRED
series; stg_financials_reported merges Finnhub filings with SEC balance
sheets; stg_news_articles types both news providers' payloads into one
layout. Everything that aggregates over bars lives in mart.mart.

Pure derivation, no API calls (registry cadence DERIVED). The rebuild is a
full per-ticker recompute: delete the ticker's staging rows, rebuild from
raw JSON payloads. Idempotent by construction, and immune to Twelve Data's
occasional historical-bar revisions (a backfill or split adjustment simply
flows through next run).
"""

from __future__ import annotations

from ..storage import Warehouse


def rebuild_prices_daily(warehouse: Warehouse, ticker: str) -> int:
    """Typed daily bars with 1-day simple returns. Rows whose payload lacks a
    valid O/H/L/C (holes in the API feed) don't make it to staging."""
    with warehouse.connect() as con:
        con.execute("DELETE FROM staging.stg_prices_daily WHERE ticker = ?", [ticker])
        con.execute(
            """
            INSERT INTO staging.stg_prices_daily
                (ticker, date, open, high, low, close, volume, return_1d)
            SELECT
                ticker,
                date,
                CAST(json_extract_string(payload, '$.open')  AS DOUBLE),
                CAST(json_extract_string(payload, '$.high')  AS DOUBLE),
                CAST(json_extract_string(payload, '$.low')   AS DOUBLE),
                CAST(json_extract_string(payload, '$.close') AS DOUBLE),
                GREATEST(CAST(json_extract_string(payload, '$.volume') AS DOUBLE), 0),
                CAST(json_extract_string(payload, '$.close') AS DOUBLE) /
                    LAG(CAST(json_extract_string(payload, '$.close') AS DOUBLE))
                        OVER (PARTITION BY ticker ORDER BY date) - 1
            FROM raw.raw_prices_daily
            WHERE ticker = ?
              AND json_extract_string(payload, '$.open')  IS NOT NULL
              AND json_extract_string(payload, '$.high')  IS NOT NULL
              AND json_extract_string(payload, '$.low')   IS NOT NULL
              AND json_extract_string(payload, '$.close') IS NOT NULL
            ORDER BY date
            """,
            [ticker],
        )
        return con.execute(
            "SELECT COUNT(*) FROM staging.stg_prices_daily WHERE ticker = ?", [ticker]
        ).fetchone()[0]


def rebuild_fred_market(warehouse: Warehouse) -> int:
    """Typed FRED index observations: raw's string `value` → DOUBLE, dropping
    the "." missing-value sentinel. Market-wide (not per ticker): the full
    table is rebuilt from raw each run — a few thousand rows, idempotent on
    the (series, date) PK."""
    with warehouse.connect() as con:
        con.execute("DELETE FROM staging.stg_fred_market")
        con.execute(
            """
            INSERT INTO staging.stg_fred_market (series, date, value)
            SELECT
                series,
                date,
                TRY_CAST(json_extract_string(payload, '$.value') AS DOUBLE)
            FROM raw.raw_fred_market
            WHERE TRY_CAST(json_extract_string(payload, '$.value') AS DOUBLE) IS NOT NULL
            """
        )
        return con.execute("SELECT COUNT(*) FROM staging.stg_fred_market").fetchone()[0]

def rebuild_financials_reported(warehouse: Warehouse, ticker: str | None = None) -> int:
    """One row per Finnhub filing, with an empty balance sheet filled from SEC.

    Finnhub's /stock/financials-reported is the filing of record (balance
    sheet, income statement, cash flow). Where its balance sheet came back
    empty, the same filing's balance sheet from SEC companyfacts, matched on
    accession number, goes into report.bs. `bs_source` records where each
    balance sheet came from: 'finnhub', 'sec', or NULL when neither has one.
    Readers parse `payload` exactly as they parsed the raw Finnhub payload.

    `ticker=None` rebuilds every ticker: the dataset builds do that first, so
    tickers outside the latest refresh still read the current merge.
    """
    where, args = ("WHERE ticker = ?", [ticker]) if ticker else ("", [])
    with warehouse.connect() as con:
        con.execute(f"DELETE FROM staging.stg_financials_reported {where}", args)
        con.execute(
            f"""
            INSERT INTO staging.stg_financials_reported
                (ticker, accession_number, year, quarter, form, filed_date, end_date, bs_source, payload)
            SELECT
                f.ticker, f.accession_number, f.year, f.quarter, f.form, f.filed_date, f.end_date,
                CASE WHEN f.has_bs THEN 'finnhub' WHEN s.payload IS NOT NULL THEN 'sec' END,
                CASE WHEN NOT f.has_bs AND s.payload IS NOT NULL
                     THEN json_merge_patch(f.payload, json_object(
                         'report', json_object('bs', json_extract(s.payload, '$.bs'))))
                     ELSE f.payload
                END
            FROM (
                SELECT
                    ticker, year, quarter, payload,
                    -- legacy payloads without an accessNumber keep their raw grain as the key
                    COALESCE(json_extract_string(payload, '$.accessNumber'),
                             year || 'Q' || quarter) AS accession_number,
                    json_extract_string(payload, '$.form') AS form,
                    TRY_CAST(substr(json_extract_string(payload, '$.filedDate'), 1, 10) AS DATE) AS filed_date,
                    TRY_CAST(substr(json_extract_string(payload, '$.endDate'), 1, 10) AS DATE) AS end_date,
                    COALESCE(json_array_length(json_extract(payload, '$.report.bs')), 0) > 0 AS has_bs
                FROM raw.raw_financials_reported
                {where}
            ) f
            LEFT JOIN raw.raw_sec_balance_sheets s
              ON s.ticker = f.ticker
             AND s.accession_number = f.accession_number
             AND COALESCE(json_array_length(json_extract(s.payload, '$.bs')), 0) > 0
            """,
            args,
        )
        return con.execute(
            f"SELECT COUNT(*) FROM staging.stg_financials_reported {where}", args
        ).fetchone()[0]


# Alpha Vantage tags every ticker an article mentions, each with a relevance
# score; below this the ticker is a passing mention, not what the article is
# about. Finnhub's `related` has no score and is kept whole.
NEWS_TICKER_MIN_RELEVANCE = 0.5


def rebuild_news_articles(warehouse: Warehouse, *, full: bool = False) -> int:
    """Typed articles from raw.raw_news_articles, restaged incrementally.

    Every source lands in the same raw table and shares three payload keys:
    `title`, `time_published` (UTC 'YYYYMMDDTHHMMSS') and `ticker_sentiment`.
    A primary source (an SEC filing, an agency release) names its `provider`
    and `feed`; for the news feeds, only a Finnhub payload has `headline`,
    which is how `provider` is told, and a Finnhub article from a per-ticker
    pull has category 'company'.

    The newest staged fetched_at is the high watermark: only rows landed at
    or after it are restaged (the batch at the watermark is re-read, which
    is harmless and can't miss a row that shares its timestamp), and a
    re-landed article gets a new fetched_at, so it is restaged too. `full=True`, or an empty table, restages everything.
    Articles missing a headline, URL or valid timestamp are dropped. Returns
    rows written.
    """
    with warehouse.connect() as con:
        # rows staged before `feed` existed are restaged in full, once
        since = None if full else con.execute(
            "SELECT CASE WHEN bool_or(feed IS NULL) THEN NULL ELSE MAX(fetched_at) END"
            " FROM staging.stg_news_articles"
        ).fetchone()[0]
        con.execute("BEGIN TRANSACTION")
        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE news_batch AS
            SELECT
                article_id,
                try_strptime(payload->>'time_published', '%Y%m%dT%H%M%S') AS published_at,
                COALESCE(payload->>'provider',
                         CASE WHEN payload->>'headline' IS NOT NULL THEN 'finnhub' ELSE 'alpha_vantage' END)
                    AS provider,
                NULLIF(trim(payload->>'source'), '') AS source,
                trim(payload->>'title') AS headline,
                NULLIF(trim(payload->>'summary'), '') AS summary,
                payload->>'url' AS url,
                -- plain US symbols only (drops CRYPTO:BTC, FOREX:USD, preferred-share
                -- lines like BNY-P-K) at or above the relevance floor, most
                -- relevant first, so tickers[1] is the stock the article is about
                list_filter(ranked, lambda t, i: list_position(ranked, t) = i) AS tickers,
                fetched_at,
                COALESCE(payload->>'feed', CASE
                    WHEN payload->>'headline' IS NULL THEN 'alpha_vantage'
                    WHEN payload->>'category' = 'company' THEN 'finnhub_company'
                    ELSE 'finnhub_general' END) AS feed,
                from_json(payload->'items', '["VARCHAR"]') AS items
            FROM (
                SELECT *, list_transform(list_reverse_sort(list_transform(list_filter(
                    COALESCE(from_json(payload->'ticker_sentiment',
                        '[{"ticker": "VARCHAR", "relevance_score": "VARCHAR"}]'), []),
                    lambda t: regexp_full_match(t.ticker, '[A-Z][A-Z.]{0,5}')
                        AND COALESCE(TRY_CAST(t.relevance_score AS DOUBLE), 1) >= ?),
                    -- position breaks ties, keeping Finnhub's own order
                    lambda t, i: {'relevance': COALESCE(TRY_CAST(t.relevance_score AS DOUBLE), 1),
                                  'position': -i, 'ticker': t.ticker})),
                    lambda t: t.ticker) AS ranked
                FROM raw.raw_news_articles
            )
            WHERE (CAST(? AS TIMESTAMPTZ) IS NULL OR fetched_at >= ?)
              AND try_strptime(payload->>'time_published', '%Y%m%dT%H%M%S') IS NOT NULL
              AND NULLIF(trim(payload->>'title'), '') IS NOT NULL
              AND NULLIF(payload->>'url', '') IS NOT NULL
            """,
            [NEWS_TICKER_MIN_RELEVANCE, since, since],
        )
        if since is None:
            con.execute("DELETE FROM staging.stg_news_articles")
        else:
            con.execute(
                "DELETE FROM staging.stg_news_articles"
                " WHERE article_id IN (SELECT article_id FROM news_batch)"
            )
        con.execute("INSERT INTO staging.stg_news_articles BY NAME SELECT * FROM news_batch")
        written = con.execute("SELECT COUNT(*) FROM news_batch").fetchone()[0]
        con.execute("DROP TABLE news_batch")
        con.execute("COMMIT")
        return written


def balance_sheet_sources(warehouse: Warehouse, since: str) -> dict[str, int]:
    """Filings filed on or after `since`, counted by where their balance sheet
    came from ('none' = neither source has one). Logged by the dataset builds
    so a source going dark shows up in the run log, not in the rankings."""
    with warehouse.connect(read_only=True) as con:
        rows = con.execute(
            """
            SELECT COALESCE(bs_source, 'none'), COUNT(*) FROM staging.stg_financials_reported
            WHERE filed_date >= ? GROUP BY 1 ORDER BY 1
            """,
            [since],
        ).fetchall()
    return dict(rows)
