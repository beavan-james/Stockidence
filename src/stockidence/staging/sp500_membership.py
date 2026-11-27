"""Staging rebuild: S&P 500 membership spells, keyed by company.

raw.raw_sp500_membership is keyed by ticker, as the source list is. A rename
ends one ticker's spell and starts the next, so the list shows Marsh &
McLennan as MMC until 2026-01-14 and MRSH after. The warehouse holds price
history under today's ticker, which reaches back across the rename. Staging
tags each spell with the company's current ticker (`ticker`) so a filter on
MRSH finds its MMC years too. The ticker as listed stays in `listed_ticker`.

RENAMES covers the renames from 2011 on, the span of the warehouse's price
history. A ticker that changed hands, like IR (Trane Technologies' ticker
until 2020-03-03, Ingersoll Rand's after), is split on the rename date.
Before then its spells belong to the new ticker (TT), and from then on to
the ticker itself.

Only the latest fetch is staged, so a spell the source list corrects away
doesn't linger. Market-wide, about 1,300 rows: rebuilt whole every run.
"""

from __future__ import annotations

from ..storage import Warehouse, one_row

# (ticker on the list, the day it stopped meaning this company, the
# company's ticker today). A company renamed twice gets one row per old
# ticker, each pointing at today's ticker.
RENAMES: tuple[tuple[str, str, str], ...] = (
    ("ABC", "2023-08-30", "COR"),  # AmerisourceBergen -> Cencora
    ("ANTM", "2022-06-28", "ELV"),  # Anthem -> Elevance Health
    ("ARNC", "2020-04-06", "HWM"),  # Arconic -> Howmet Aerospace
    ("BBT", "2019-12-09", "TFC"),  # BB&T -> Truist
    ("BHGE", "2019-10-18", "BKR"),  # Baker Hughes, a GE company -> Baker Hughes
    ("BK", "2026-05-21", "BNY"),  # Bank of New York Mellon -> BNY
    ("BLL", "2022-05-10", "BALL"),  # Ball
    ("CBS", "2019-12-05", "PSKY"),  # CBS -> ViacomCBS -> Paramount -> Paramount Skydance
    ("CDAY", "2024-02-01", "DAY"),  # Ceridian -> Dayforce
    ("COG", "2021-10-04", "CTRA"),  # Cabot Oil & Gas -> Coterra
    ("CTL", "2020-09-18", "LUMN"),  # CenturyLink -> Lumen
    ("DISCA", "2022-04-11", "WBD"),  # Discovery -> Warner Bros. Discovery
    ("DISCK", "2022-04-11", "WBD"),
    ("DWDP", "2019-06-03", "DD"),  # DowDuPont -> DuPont de Nemours
    ("FB", "2022-06-09", "META"),  # Facebook -> Meta Platforms
    ("FI", "2025-11-11", "FISV"),  # Fiserv traded as FI from 2023-06-07
    ("FLT", "2024-03-25", "CPAY"),  # FleetCor -> Corpay
    ("HCP", "2019-11-05", "DOC"),  # HCP -> Healthpeak (PEAK, then DOC)
    ("HRS", "2019-06-01", "LHX"),  # Harris -> L3Harris
    ("IR", "2020-03-03", "TT"),  # Ingersoll-Rand plc -> Trane; IR then went to Ingersoll Rand Inc.
    ("JEC", "2019-12-10", "J"),  # Jacobs Engineering -> Jacobs
    ("KORS", "2019-01-02", "CPRI"),  # Michael Kors -> Capri
    ("MMC", "2026-01-14", "MRSH"),  # Marsh & McLennan -> Marsh McLennan
    ("MYL", "2020-11-17", "VTRS"),  # Mylan -> Viatris
    ("NLOK", "2022-11-08", "GEN"),  # NortonLifeLock -> Gen Digital
    ("PARA", "2025-08-08", "PSKY"),
    ("PEAK", "2024-03-04", "DOC"),
    ("PKI", "2023-05-16", "RVTY"),  # PerkinElmer -> Revvity
    ("PX", "2018-11-06", "LIN"),  # Praxair -> Linde
    ("RE", "2023-07-10", "EG"),  # Everest Re -> Everest Group
    ("SQ", "2025-01-21", "XYZ"),  # Block; joined the index as XYZ, so no SQ spells
    ("SYMC", "2019-11-05", "GEN"),  # Symantec -> NortonLifeLock -> Gen Digital
    ("TMK", "2019-08-08", "GL"),  # Torchmark -> Globe Life
    ("UTX", "2020-04-03", "RTX"),  # United Technologies -> RTX
    ("VIAC", "2022-02-17", "PSKY"),
    ("WLTW", "2022-01-10", "WTW"),  # Willis Towers Watson
)


def rebuild_sp500_membership(warehouse: Warehouse) -> int:
    """Spells from the latest fetch, split on rename dates and tagged with
    the company's current ticker. end_date is the first day out of the
    index, NULL for a current member."""
    with warehouse.connect() as con:
        con.execute("DELETE FROM staging.stg_sp500_membership")
        con.execute(
            f"""
            INSERT INTO staging.stg_sp500_membership
                (listed_ticker, start_date, end_date, ticker)
            WITH latest AS (
                SELECT
                    ticker,
                    start_date,
                    TRY_CAST(NULLIF(json_extract_string(payload, '$.end_date'), '') AS DATE)
                        AS end_date
                FROM raw.raw_sp500_membership
                WHERE index_name = 'SP500'
                  AND fetched_at = (
                      SELECT MAX(fetched_at) FROM raw.raw_sp500_membership
                      WHERE index_name = 'SP500'
                  )
            ),
            renames (listed_ticker, renamed_on, ticker) AS (
                VALUES {", ".join("(?, CAST(? AS DATE), ?)" for _ in RENAMES)}
            )
            -- the part of a spell before its ticker's rename: today's ticker
            SELECT l.ticker, l.start_date, LEAST(COALESCE(l.end_date, r.renamed_on), r.renamed_on),
                   r.ticker
            FROM latest l JOIN renames r ON l.ticker = r.listed_ticker
            WHERE l.start_date < r.renamed_on
            UNION ALL
            -- the rest: the ticker stands for itself
            SELECT l.ticker, GREATEST(l.start_date, COALESCE(r.renamed_on, l.start_date)),
                   l.end_date, l.ticker
            FROM latest l LEFT JOIN renames r ON l.ticker = r.listed_ticker
            WHERE r.renamed_on IS NULL OR l.end_date IS NULL OR l.end_date > r.renamed_on
            """,
            [value for rename in RENAMES for value in rename],
        )
        return one_row(con.execute("SELECT COUNT(*) FROM staging.stg_sp500_membership"))[0]
