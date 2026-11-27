"""Build the ML training dataset, parameterized by bar frequency.

For each (ticker, period label), assembles:
  - Price-derived features from m_technical_indicators (daily snapshot as-of
    the period's last trading day — the same day the anchor close is known)
  - Rolling analytics from m_advanced_analytics (same snapshot semantics)
  - PIT fundamentals from raw_financials_reported (latest available quarterly report)
  - Static sector label from raw_company_profile
  - S&P 500 membership (stg_sp500_membership): `in_index` says the company
    was in the index on the snapshot day, `sp500_status` where it stands on
    today's list. Training and backtests keep in_index rows only, so a stock
    counts only while it was in the index, not because it is in it today
  - Target: next-period return (anchor close-to-close); weekly instead labels
    next-week and next-13-week returns entered at the next week's open

Mart bars are labeled at period START (date_trunc) but hold the period-END
close (last(close)), so features are snapshotted on the period's last trading
day, never on the label itself — that keeps features and close on the same day
without lookahead.

Feature sets are frequency-specific:
  - monthly: 14-day technical indicators + the 6 static fundamentals
  - weekly: the monthly set plus quarterly-scale momentum at weekly
    resolution and short-horizon signals (Stocks of the Week)
  - quarterly: macro momentum (price_to_sma200, return_3m/12m, 52wk-high
    distance, atr_pct, 252-day vol & drawdown) + fundamental velocity
    (static ratios plus their quarter-over-quarter change)

Grains: monthly (default), weekly, quarterly.
Output: Model/datasets/train_dataset.parquet (daily) /
        train_dataset_{freq}.parquet (weekly/monthly/quarterly)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from stockidence.staging.sp500_membership import RENAMES
from stockidence.storage import Warehouse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Feature constants ──────────────────────────────────────────────────────────

# From m_technical_indicators (month-end snapshot)
TI_FEATURES = [
    "sma_20",
    "sma_50",
    "sma_200",
    "ema_12",
    "ema_26",
    "rsi_14",
    "adx_14",
    "atr_14",
    "macd_hist",
    "stoch_k_14",
    "stoch_d_14",
    "cci_20",
]

# From m_advanced_analytics (month-end snapshot)
AA_FEATURES = [
    "stddev_252",
    "max_drawdown_252",
]

# From mart.m_fred_market — market-wide regime (VIX + S&P500), joined PIT
# as-of each period-end. vix_pctile_252 is derived below from the daily level.
MARKET_FEATURES = [
    "vix",
    "vix_pctile_252",
    "vix_chg_21d",
    "spx_ret_21d",
    "spx_ret_63d",
    "spx_ret_252d",
]

# Derived from raw_financials_reported (PIT)
FUNDAMENTAL_FEATURES = [
    "roe",  # net_income / equity
    "roa",  # net_income / assets
    "debt_equity",  # liabilities / equity
    "current_ratio",  # current_assets / current_liabilities
    "cash_to_assets",  # cash / total_assets
    "fcf_to_assets",  # (ocf - capex) / total_assets
]

# ── Rolling return-distribution statistics (computed per ticker, PIT) ────────
# Computed on the period-grain close series after assembly; each row uses only
# closes through its own period-end (no lookahead). Window is in periods.
ROLLING_RET_WINDOW = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 12}
ROLLING_BETA_WINDOW = {"daily": 504, "weekly": 104, "monthly": 24, "quarterly": 24}
ROLLING_FEATURES = [
    "roll_sharpe",  # trailing mean/std of period returns (annualized)
    "roll_skew",  # trailing skewness of period returns
    "roll_kurt",  # trailing excess kurtosis (fat-tail regime)
    "roll_downside_dev",  # std of negative period returns (semi-deviation)
    "roll_var95",  # 5% historical VaR of period returns (loss tail)
    "roll_beta",  # trailing beta of name vs S&P500 period returns
]

ALL_FEATURES = TI_FEATURES + AA_FEATURES + FUNDAMENTAL_FEATURES + MARKET_FEATURES + ROLLING_FEATURES

# ── Quarterly-specific feature set ─────────────────────────────────────────────
# The quarterly dataset uses macro-scale momentum + fundamental velocity instead
# of 14-day indicators, which are a poor match for a ~3-month target window.
QUARTERLY_TI_FEATURES = [
    "sma_200",  # trend context for price_to_sma200
    "atr_14",  # input to atr_pct
]
QUARTERLY_AA_FEATURES = [
    "stddev_252",  # 252-day realized vol (structural context)
    "max_drawdown_252",  # deepest trailing drawdown
    "max_252",  # 52-week high (input to distance_from_52wk_high)
]

# Static fundamentals + quarter-over-quarter change (velocity). Trees see
# "ROE rose from 5% to 15%" rather than just a static level.
CHG_FEATURES = ["roe", "roa", "fcf_to_assets", "debt_equity"]
QUARTERLY_FUND_FEATURES = FUNDAMENTAL_FEATURES + [f"{c}_chg_qoq" for c in CHG_FEATURES]

QUARTERLY_PRICE_FEATURES = [
    "price_to_sma200",
    "stddev_252",
    "max_drawdown_252",
    "atr_pct",
    "return_3m",
    "return_12m",
    "distance_from_52wk_high",
]
QUARTERLY_ALL_FEATURES = (
    QUARTERLY_PRICE_FEATURES + QUARTERLY_FUND_FEATURES + MARKET_FEATURES + ROLLING_FEATURES
)

# ── Weekly-specific feature set ────────────────────────────────────────────────
# Friday-close snapshots for the Stocks of the Week list. The quarterly price
# features carry over at weekly resolution (return_3m = 13 weeks, return_12m =
# 52 weeks) so a quarterly-horizon target can be ranked every week; the
# short-horizon signals are candidates for the next-week target. The legacy
# weekly columns (TI_FEATURES, AA_FEATURES) stay in the frame too.
WEEKLY_TI_FEATURES = TI_FEATURES + ["bb_upper_20", "bb_lower_20"]
WEEKLY_AA_FEATURES = AA_FEATURES + ["max_252", "mean_252"]
WEEKLY_SHORT_FEATURES = [
    "return_1w",
    "return_4w",
    "rsi_14",
    "price_to_sma20",
    "price_to_sma50",
    "stoch_k_14",
    "cci_20",
    "adx_14",
    "macd_hist_pct",
    "bb_pctb",
    "volume_ratio_13w",
    "range_1w",
    "vol_ratio",
]
WEEKLY_ALL_FEATURES = QUARTERLY_PRICE_FEATURES + FUNDAMENTAL_FEATURES + WEEKLY_SHORT_FEATURES

# Forward horizons (in weeks) labelled on every weekly row. Both are measured
# from the NEXT week's open: a list published after Friday's close can first
# be bought at Monday's open, so the Friday close is not a tradeable entry.
WEEKLY_HORIZONS = {"target_return": 1, "target_return_13w": 13}

# US session close; a week counts as finished once its Friday close passes.
MARKET_TZ = "America/New_York"

# Categorical features are merged per ticker (not snapshot per period).
CATEGORICAL_FEATURES = ["sector"]

# ── Training universe ────────────────────────────────────────────────────────────
# The curated universe the dataset is built for. The warehouse may hold a much
# wider ingestion universe (e.g. the full S&P 500); this restricts every load
# to the names the model should actually be trained on. Override at runtime
# with `--tickers` / `--tickers-file`. None = use every ticker in the warehouse.
TRAIN_TICKERS: list[str] | None = None

# Finnhub `finnhubIndustry` → coarse GICS-like sector. Finnhub returns 33
# granular industries; grouping to ~11 sectors keeps tree splits from
# memorizing near-singleton buckets (Biotech=4, Media=3, ...). Only tickers
# whose industry is absent from the map fall through as NaN.
SECTOR_MAP = {
    # Technology
    "Technology": "Technology",
    "Semiconductors": "Technology",
    # Energy
    "Energy": "Energy",
    # Financials
    "Banking": "Financials",
    "Financial Services": "Financials",
    "Insurance": "Financials",
    # Healthcare
    "Health Care": "Healthcare",
    "Pharmaceuticals": "Healthcare",
    "Biotechnology": "Healthcare",
    "Life Sciences Tools & Services": "Healthcare",
    # Consumer Discretionary
    "Retail": "Consumer Discretionary",
    "Hotels, Restaurants & Leisure": "Consumer Discretionary",
    "Consumer products": "Consumer Discretionary",
    "Textiles, Apparel & Luxury Goods": "Consumer Discretionary",
    # Consumer Staples
    "Beverages": "Consumer Staples",
    "Food Products": "Consumer Staples",
    # Industrials
    "Aerospace & Defense": "Industrials",
    "Machinery": "Industrials",
    "Electrical Equipment": "Industrials",
    "Commercial Services & Supplies": "Industrials",
    "Logistics & Transportation": "Industrials",
    "Industrial Conglomerates": "Industrials",
    "Road & Rail": "Industrials",
    "Professional Services": "Industrials",
    # Materials
    "Chemicals": "Materials",
    "Metals & Mining": "Materials",
    "Construction": "Materials",
    "Packaging": "Materials",
    # Communication Services
    "Media": "Communication Services",
    "Communications": "Communication Services",
    "Telecommunication": "Communication Services",
    # Real Estate / Utilities
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}


# ── Data loading helpers ────────────────────────────────────────────────────────


def _ticker_filter(tickers: list[str] | None) -> tuple[str, list[str]]:
    """SQL WHERE fragment + params restricting a query to the training universe.

    Returns ("", []) when the universe is unrestricted so existing callers run
    unchanged. Unsafe characters don't matter: values are passed as query
    parameters, never interpolated.
    """
    if not tickers:
        return "", []
    placeholders = ", ".join("?" for _ in tickers)
    return f"WHERE ticker IN ({placeholders})", list(tickers)


def _load_price(
    wh: Warehouse, freq: str = "monthly", tickers: list[str] | None = None
) -> pd.DataFrame:
    """Load anchor OHLCV bars labeled at period start (mart convention).

    Weekly/monthly come straight from the mart; quarterly is resampled from
    the monthly bars (close = last month's end-of-month close); daily comes
    straight from the cleaned staging bars (its own period).
    """
    where, params = _ticker_filter(tickers)
    if freq in ("weekly", "monthly"):
        table = f"mart.m_prices_{freq}"
        with wh.connect(read_only=True) as con:
            df = pd.read_sql(
                f"SELECT ticker, date, open, high, low, close, volume "
                f"FROM {table} {where} ORDER BY ticker, date",
                con,
                params=params,
            )
    elif freq == "daily":
        with wh.connect(read_only=True) as con:
            df = pd.read_sql(
                f"SELECT ticker, date, open, high, low, close, volume "
                f"FROM staging.stg_prices_daily {where} ORDER BY ticker, date",
                con,
                params=params,
            )
    elif freq == "quarterly":
        with wh.connect(read_only=True) as con:
            base = pd.read_sql(
                f"SELECT ticker, date, open, high, low, close, volume "
                f"FROM mart.m_prices_monthly {where} ORDER BY ticker, date",
                con,
                params=params,
            )
        base["date"] = pd.to_datetime(base["date"])
        base["label"] = base["date"].dt.to_period("Q").dt.start_time.dt.normalize()
        df = (
            base.groupby(["ticker", "label"], as_index=False)
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .rename(columns={"label": "date"})
        )
    else:
        raise ValueError(f"unknown freq: {freq}")

    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_technical_indicators(
    wh: Warehouse, feature_cols: list[str] | None = None, tickers: list[str] | None = None
) -> pd.DataFrame:
    """Load daily technical indicators."""
    cols = feature_cols if feature_cols is not None else TI_FEATURES
    where, params = _ticker_filter(tickers)
    with wh.connect(read_only=True) as con:
        sql_cols = ["ticker", "date"] + cols
        sql = f"SELECT {', '.join(sql_cols)} FROM mart.m_technical_indicators {where} ORDER BY ticker, date"
        df = pd.read_sql(sql, con, params=params)
    df["date"] = pd.to_datetime(df["date"])
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_advanced_analytics(
    wh: Warehouse, feature_cols: list[str] | None = None, tickers: list[str] | None = None
) -> pd.DataFrame:
    """Load daily advanced analytics."""
    cols = feature_cols if feature_cols is not None else AA_FEATURES
    where, params = _ticker_filter(tickers)
    with wh.connect(read_only=True) as con:
        sql_cols = ["ticker", "date", "close"] + cols
        sql = f"SELECT {', '.join(sql_cols)} FROM mart.m_advanced_analytics {where} ORDER BY ticker, date"
        df = pd.read_sql(sql, con, params=params)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["close"] + cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_financials(wh: Warehouse, tickers: list[str] | None = None) -> pd.DataFrame:
    """Load PIT financials and extract key metrics from the payload JSON.

    Reads staging, not raw: stg_financials_reported is Finnhub's filings with
    any empty balance sheet filled from the same filing on SEC EDGAR.
    """
    import json

    where, params = _ticker_filter(tickers)
    with wh.connect(read_only=True) as con:
        rows = con.execute(
            f"SELECT ticker, year, quarter, payload FROM staging.stg_financials_reported {where}",
            params,
        ).fetchall()

    # XBRL concept aliases per metric, in precedence order. Covers:
    #   us-gaap_* standard names, unprefixed Finnhub-normalized names
    #   (Assets instead of us-gaap_Assets), and *ContinuingOperations
    #   variants. Company-specific prefixes (v_, cat_, ko_...) are custom
    #   line items and are intentionally NOT mapped.
    ALIASES = {
        "assets": ["us-gaap_Assets", "Assets"],
        "liabilities": ["us-gaap_Liabilities", "Liabilities"],
        "equity": [
            "us-gaap_StockholdersEquity",
            "StockholdersEquity",
            "us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "current_assets": ["us-gaap_AssetsCurrent", "AssetsCurrent"],
        "current_liabilities": ["us-gaap_LiabilitiesCurrent", "LiabilitiesCurrent"],
        "cash": [
            "us-gaap_CashAndCashEquivalentsAtCarryingValue",
            "CashAndCashEquivalentsAtCarryingValue",
        ],
        "net_income": [
            "us-gaap_NetIncomeLoss",
            "NetIncomeLoss",
            "us-gaap_ProfitLoss",
            "ProfitLoss",
            "us-gaap_NetIncomeLossIncludingPortionAttributableToNoncontrollingInterest",
        ],
        "ocf": [
            "us-gaap_NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivities",
            "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
        "capex": [
            "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "us-gaap_PaymentsToAcquireProductiveAssets",
            "PaymentsToAcquireProductiveAssets",
            "us-gaap_PaymentsToAcquirePropertyPlantAndEquipmentAndPaymentsForProceedsFromSaleOfPropertyPlantAndEquipment",
            "us-gaap_CapitalExpendituresIncurredButNotYetPaid",
        ],
    }

    records = []
    for ticker, year, quarter, payload_str in rows:
        payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        report = payload.get("report", {})

        # Merge bs + cf + ic into one concept dict. First-seen wins, so
        # balance-sheet values take precedence over duplicated cash-flow values.
        concepts: dict[str, float] = {}
        for section in ("bs", "cf", "ic"):
            for item in report.get(section, []):
                concepts.setdefault(item["concept"], item.get("value"))

        def _to_float(v) -> float | None:
            """Coerce a payload value to float, tolerating junk like 'N/A'."""
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _get(*keys: str) -> float | None:
            """First matching alias value for a metric family."""
            for key in keys:
                v = _to_float(concepts.get(key))  # noqa: B023 - only called in this iteration
                if v is not None:
                    return v
            return None

        total_assets = _get(*ALIASES["assets"])
        liabilities = _get(*ALIASES["liabilities"])
        equity = _get(*ALIASES["equity"])
        current_assets = _get(*ALIASES["current_assets"])
        current_liabilities = _get(*ALIASES["current_liabilities"])
        cash = _get(*ALIASES["cash"])
        net_income = _get(*ALIASES["net_income"])
        ocf = _get(*ALIASES["ocf"])
        capex = _get(*ALIASES["capex"])

        # Accounting identity fallback: Assets = Liabilities + Equity.
        # Many filings report only LiabilitiesAndStockholdersEquity without
        # a standalone liabilities line — derive it instead of dropping.
        if liabilities is None and total_assets is not None and equity is not None:
            liabilities = total_assets - equity

        roe = net_income / equity if net_income and equity and equity > 0 else None
        roa = (
            net_income / total_assets if net_income and total_assets and total_assets > 0 else None
        )
        debt_equity = liabilities / equity if liabilities and equity and equity > 0 else None
        current_ratio = (
            current_assets / current_liabilities
            if current_assets and current_liabilities and current_liabilities > 0
            else None
        )
        cash_to_assets = cash / total_assets if cash and total_assets and total_assets > 0 else None
        fcf = (ocf - capex) if ocf is not None and capex is not None else None
        fcf_to_assets = (
            fcf / total_assets if fcf is not None and total_assets and total_assets > 0 else None
        )

        # Filing date determines PIT availability
        filed_date = payload.get("filedDate", "")
        end_date = payload.get("endDate", "")

        records.append(
            {
                "ticker": ticker,
                "year": year,
                "quarter": quarter,
                "filed_date": pd.to_datetime(filed_date) if filed_date else None,
                "end_date": pd.to_datetime(end_date) if end_date else None,
                "roe": roe,
                "roa": roa,
                "debt_equity": debt_equity,
                "current_ratio": current_ratio,
                "cash_to_assets": cash_to_assets,
                "fcf_to_assets": fcf_to_assets,
            }
        )

    fin = pd.DataFrame(records)

    # Quarter-over-quarter change: per ticker, previous reported period. A
    # rising 5%->15% ROE reads differently from a falling 25%->15% ROE, so
    # the velocity is fed in alongside the static level. Computed per filing
    # row so the PIT join attaches it with the right report.
    fin = fin.sort_values(["ticker", "end_date"])
    for col in CHG_FEATURES:
        fin[f"{col}_chg_qoq"] = fin.groupby("ticker")[col].diff()

    return fin


def _load_market(wh: Warehouse) -> pd.DataFrame:
    """Load the daily market-regime table (VIX + S&P500 momentum) from mart.

    Market-wide: no ticker dimension, so the dataset joins it per period-end
    date rather than per (ticker, date). The vix_pctile_252 regime feature is
    computed here on the FULL daily series (before the as-of join) so it is
    never contaminated by the label window.
    """
    with wh.connect(read_only=True) as con:
        m = pd.read_sql(
            "SELECT date, spx, vix, spx_ret_21d, spx_ret_63d, spx_ret_252d, "
            "vix_chg_5d, vix_chg_21d FROM mart.m_fred_market ORDER BY date",
            con,
        )
    m["date"] = pd.to_datetime(m["date"])
    for col in m.columns.difference(["date"]):
        m[col] = pd.to_numeric(m[col], errors="coerce")
    # rolling 252-day percentile rank of the VIX level — what regime the
    # market sits in as of that date (PIT, computed before any row join).
    m["vix_pctile_252"] = (
        m["vix"].rolling(252, min_periods=63).apply(lambda w: (w <= w.iloc[-1]).mean(), raw=False)
    )
    return m


def _merge_market(dataset: pd.DataFrame, market: pd.DataFrame, asof: pd.DataFrame) -> pd.DataFrame:
    """Join market features as-of each period-end (backward, no ticker key).

    `asof` maps (ticker, date) labels → the period's last trading day; each
    label row gets the latest market observation on or before that day. Rows
    before the S&P500 series starts (~2016 on FRED) get NaN market features
    rather than being dropped — the model treats missing as unknown.
    """
    keys = asof[["ticker", "date", "asof_date"]].rename(
        columns={"asof_date": "asof", "date": "label"}
    )
    joined = pd.merge_asof(
        keys.sort_values("asof"),
        market.sort_values("date"),
        left_on="asof",
        right_on="date",
        direction="backward",
    )
    joined = joined[["ticker", "label"] + MARKET_FEATURES].rename(columns={"label": "date"})
    return dataset.merge(joined, on=["ticker", "date"], how="left")


def _load_company_profile(wh: Warehouse, tickers: list[str] | None = None) -> pd.DataFrame:
    """Load the coarse sector label per ticker from raw_company_profile.

    Finnhub classifies each company with a granular `finnhubIndustry`;
    SECTOR_MAP collapses that to ~11 GICS-like sectors. The label is
    Finnhub's *current* classification applied across all history —
    companies almost never change their industry, so no PIT handling.
    """
    import json

    where, params = _ticker_filter(tickers)
    with wh.connect(read_only=True) as con:
        rows = con.execute(
            f"SELECT ticker, payload FROM raw.raw_company_profile {where}",
            params,
        ).fetchall()

    records = []
    for ticker, payload_str in rows:
        payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        industry = payload.get("finnhubIndustry")
        records.append({"ticker": ticker, "sector": SECTOR_MAP.get(industry)})

    return pd.DataFrame(records)


def _load_sp500_membership(wh: Warehouse) -> pd.DataFrame:
    """S&P 500 membership spells, tagged with each company's ticker today.
    Empty when the list hasn't landed yet (or the table predates it)."""
    cols = ["listed_ticker", "start_date", "end_date", "ticker"]
    with wh.connect(read_only=True) as con:
        exists = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'staging' AND table_name = 'stg_sp500_membership'"
        ).fetchone()[0]
        if not exists:
            return pd.DataFrame(columns=cols)
        m = con.execute(f"SELECT {', '.join(cols)} FROM staging.stg_sp500_membership").df()
    m["start_date"] = pd.to_datetime(m["start_date"])
    m["end_date"] = pd.to_datetime(m["end_date"])
    return m


# ── PIT join logic ──────────────────────────────────────────────────────────────


def _ticker_key(ticker: str) -> str:
    """One spelling per share class: the warehouse has BF-B, the list BF.B."""
    return str(ticker).upper().replace("-", ".")


def _standing_tickers(
    tickers: list[str], membership: pd.DataFrame, renames=RENAMES
) -> pd.DataFrame:
    """Which company each warehouse ticker stands for, and whether it is the
    one ticker that does.

    A ticker stands for the company its latest spell on the list belongs to
    (MMC's spells are Marsh McLennan's, now MRSH), or the company a rename
    took it to when the list never had it (SQ -> XYZ), else itself. When the
    warehouse holds two tickers for one company (MMC and MRSH carry the same
    price history), the company's ticker today wins; failing that, the one
    listed most recently. The others are duplicates and never count.
    """
    listed = membership.assign(key=membership["listed_ticker"].map(_ticker_key))
    latest = listed.sort_values("start_date").groupby("key").last()
    company = latest["ticker"].map(_ticker_key).to_dict()
    renamed = {_ticker_key(old): _ticker_key(new) for old, _, new in renames}

    out = pd.DataFrame({"ticker": list(tickers)})
    out["key"] = out["ticker"].map(_ticker_key)
    out["company"] = [company.get(k, renamed.get(k, k)) for k in out["key"]]
    out["listed_since"] = out["key"].map(latest["start_date"])
    out["is_company"] = out["key"] == out["company"]
    pick = out.sort_values(
        ["is_company", "listed_since", "ticker"], ascending=[False, False, True], na_position="last"
    )
    chosen = set(pick.drop_duplicates("company")["ticker"])
    out["standing"] = out["ticker"].isin(chosen)
    return out[["ticker", "company", "standing"]]


def _index_membership(
    rows: pd.DataFrame, membership: pd.DataFrame, renames=RENAMES
) -> pd.DataFrame:
    """Point-in-time S&P 500 membership for (ticker, snapshot day) rows.

    `in_index`: the ticker stands for its company and the company was in the
    index on `asof`, its snapshot day (a spell runs from start_date up to,
    not including, end_date). `sp500_status`, per ticker, from today's list:
    "current", "former", "never" (not on the list since 1996) or "duplicate"
    (another warehouse ticker stands for the company). With no list landed,
    every row counts ("unknown"), as before the filter existed.
    """
    if membership.empty:
        return pd.DataFrame({"in_index": True, "sp500_status": "unknown"}, index=rows.index)

    standing = _standing_tickers(rows["ticker"].unique().tolist(), membership, renames)
    spells = membership.assign(company=membership["ticker"].map(_ticker_key))
    by_company = spells.groupby("company")["end_date"]
    status = standing["company"].map(
        lambda c: (
            "never"
            if c not in by_company.groups
            else "current"
            if by_company.get_group(c).isna().any()
            else "former"
        )
    )
    status = status.where(standing["standing"], "duplicate")
    standing = standing.assign(sp500_status=status.values)

    keyed = rows[["ticker", "asof"]].reset_index(names="row").merge(standing, on="ticker")
    hits = keyed[keyed["standing"]].merge(
        spells[["company", "start_date", "end_date"]], on="company"
    )
    covered = (hits["start_date"] <= hits["asof"]) & (
        hits["end_date"].isna() | (hits["asof"] < hits["end_date"])
    )
    in_rows = set(hits.loc[covered, "row"])

    keyed = keyed.set_index("row").reindex(rows.index)
    return pd.DataFrame(
        {
            "in_index": rows.index.isin(list(in_rows)),
            "sp500_status": keyed["sp500_status"].values,
        },
        index=rows.index,
    )


def _pit_join_fundamentals(
    monthly: pd.DataFrame,
    financials: pd.DataFrame,
    fund_cols: list[str] | None = None,
) -> pd.DataFrame:
    """For each (ticker, period-end), attach the latest quarterly report
    whose filed_date <= period-end (point-in-time correct)."""
    if fund_cols is None:
        fund_cols = FUNDAMENTAL_FEATURES
    if financials.empty:
        for col in fund_cols:
            monthly[col] = np.nan
        return monthly

    financials = financials.dropna(subset=["filed_date"]).copy()

    # Standardize join date precision across both DataFrames
    monthly = monthly.copy()
    monthly["date"] = pd.to_datetime(monthly["date"]).astype("datetime64[ns]")
    financials["filed_date"] = pd.to_datetime(financials["filed_date"]).astype("datetime64[ns]")

    # Prepare right dataframe and rename join column
    fin_cols = ["ticker", "filed_date"] + fund_cols
    fin_df = financials[fin_cols].rename(columns={"filed_date": "date"})

    # Sort required for pd.merge_asof
    monthly = monthly.sort_values("date")
    fin_df = fin_df.sort_values("date")

    result = pd.merge_asof(
        monthly,
        fin_df,
        on="date",
        by="ticker",
        direction="backward",
    )
    return result


# ── Feature engineering ──────────────────────────────────────────────────────────


def _period_end_dates(daily_dates: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Map each anchor label (period start) → the period's last trading day.

    Features must be snapshotted on the day the anchor close is known (the
    period-end bar), not on the mart's period-start label — otherwise they'd
    be a full period stale relative to the close.
    """
    d = daily_dates[["ticker", "date"]].copy()
    if freq == "daily":
        d["label"] = d["date"]
    elif freq == "weekly":
        d["label"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    elif freq == "monthly":
        d["label"] = d["date"].dt.to_period("M").dt.start_time.dt.normalize()
    elif freq == "quarterly":
        d["label"] = d["date"].dt.to_period("Q").dt.start_time.dt.normalize()
    else:
        raise ValueError(f"unknown freq: {freq}")

    return (
        d.groupby(["ticker", "label"], as_index=False)["date"]
        .max()
        .rename(columns={"date": "asof_date", "label": "date"})
    )


def _snapshot_daily(
    daily: pd.DataFrame,
    anchor: pd.DataFrame,
    feature_cols: list[str],
    asof_col: str = "asof_date",
) -> pd.DataFrame:
    """Snapshot daily features as-of each anchor's period-end date.

    Returns rows keyed on the anchor's (ticker, date) label so the caller can
    merge straight back onto the dataset.
    """
    keys = anchor[["ticker", asof_col, "date"]].rename(columns={asof_col: "asof", "date": "label"})
    res = pd.merge_asof(
        keys.sort_values("asof"),
        daily[["ticker", "date"] + feature_cols].sort_values("date"),
        left_on="asof",
        right_on="date",
        by="ticker",
        direction="backward",
    )
    res = res[["ticker", "label"] + feature_cols].rename(columns={"label": "date"})
    return res


def _add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add ratio features that combine price and fundamentals."""
    # Price-to-SMA ratios (trend signal)
    if "sma_20" in df.columns:
        df["price_to_sma20"] = df["close"] / df["sma_20"]
    if "sma_50" in df.columns:
        df["price_to_sma50"] = df["close"] / df["sma_50"]
    if "sma_200" in df.columns:
        df["price_to_sma200"] = df["close"] / df["sma_200"]

    # Distance from 52-week high/low (from advanced analytics)
    if "max_252" in df.columns and "min_252" in df.columns:
        range_52w = df["max_252"] - df["min_252"]
        df["dist_from_52w_high"] = np.where(
            range_52w != 0, (df["close"] - df["max_252"]) / range_52w, np.nan
        )
        df["dist_from_52w_low"] = np.where(
            range_52w != 0, (df["close"] - df["min_252"]) / range_52w, np.nan
        )

    # ATR normalized by price (volatility proxy)
    if "atr_14" in df.columns:
        df["atr_pct"] = df["atr_14"] / df["close"]

    # Volatility ratio (stddev / mean — normalized volatility)
    if "stddev_252" in df.columns and "mean_252" in df.columns:
        df["vol_ratio"] = np.where(df["mean_252"] != 0, df["stddev_252"] / df["mean_252"], np.nan)

    return df


def _add_quarterly_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derived features for the quarterly dataset (macro-scale momentum).

    Uses ratios that span the target window (3m/12m) rather than 14-day
    indicators. All values are known as-of the row's period-end close — the
    momentum return is the *previous* quarter roll, PIT-correct.
    """
    if "sma_200" in df.columns:
        df["price_to_sma200"] = df["close"] / df["sma_200"]
    if "atr_14" in df.columns:
        df["atr_pct"] = df["atr_14"] / df["close"]
    if "max_252" in df.columns:
        df["distance_from_52wk_high"] = df["close"] / df["max_252"] - 1

    df = df.sort_values(["ticker", "date"])
    df["return_3m"] = df.groupby("ticker")["close"].pct_change()
    df["return_12m"] = df.groupby("ticker")["close"].pct_change(4)
    return df


def _add_weekly_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derived features for the weekly dataset, on top of _add_derived_features.

    Quarterly-scale momentum at weekly resolution plus short-horizon signals
    (last week's move, oscillators, volume surge). Everything is known at the
    row's Friday close; volume_ratio_13w compares this week's volume with the
    13 weeks BEFORE it, so the current week never enters its own baseline.
    """
    df["distance_from_52wk_high"] = df["close"] / df["max_252"] - 1
    df["macd_hist_pct"] = df["macd_hist"] / df["close"]
    band = df["bb_upper_20"] - df["bb_lower_20"]
    df["bb_pctb"] = np.where(band > 0, (df["close"] - df["bb_lower_20"]) / band, np.nan)
    df["range_1w"] = (df["high"] - df["low"]) / df["close"]

    df = df.sort_values(["ticker", "date"])
    g = df.groupby("ticker")
    df["return_1w"] = g["close"].pct_change()
    df["return_4w"] = g["close"].pct_change(4)
    df["return_3m"] = g["close"].pct_change(13)
    df["return_12m"] = g["close"].pct_change(52)
    baseline = g["volume"].transform(lambda s: s.shift(1).rolling(13, min_periods=8).mean())
    df["volume_ratio_13w"] = df["volume"] / baseline.replace(0, np.nan)
    return df


# ── Rolling return-distribution statistics ─────────────────────────────────────


def _rolling_sharpe(
    ret: pd.Series, win: int, periods_per_year: float, min_periods: int | None = None
) -> pd.Series:
    """Trailing mean/std ratio of period returns, annualized."""
    mp = min_periods or max(3, win // 2)
    m = ret.rolling(win, min_periods=mp).mean()
    s = ret.rolling(win, min_periods=mp).std(ddof=0)
    return m / s.replace(0, np.nan) * np.sqrt(periods_per_year)


def _rolling_skew(ret: pd.Series, win: int, min_periods: int | None = None) -> pd.Series:
    """Trailing skewness (Fisher-Pearson, sample) of period returns."""
    mp = min_periods or max(4, win // 2)
    return ret.rolling(win, min_periods=mp).skew()


def _rolling_kurt(ret: pd.Series, win: int, min_periods: int | None = None) -> pd.Series:
    """Trailing excess kurtosis of period returns; NaN until enough obs."""
    mp = min_periods or max(4, win // 2)
    return ret.rolling(win, min_periods=mp).kurt()


def _rolling_downside_dev(ret: pd.Series, win: int, min_periods: int | None = None) -> pd.Series:
    """Semi-deviation: std of only the non-positive period returns."""
    # A window rarely holds a full `win` of non-positive returns, so keep the
    # required count modest (the stat is a tail measure, not a density estimate).
    mp = min_periods or max(3, win // 4)
    neg = ret.where(ret <= 0)
    return neg.rolling(win, min_periods=mp).std(ddof=0)


def _rolling_var95(ret: pd.Series, win: int, min_periods: int | None = None) -> pd.Series:
    """5% historical VaR: negative of the 5th percentile of period returns."""
    mp = min_periods or max(5, win // 2)
    return -ret.rolling(win, min_periods=mp).quantile(0.05)


def _rolling_beta(
    name_ret: pd.Series, mkt_ret: pd.Series, win: int, min_periods: int | None = None
) -> pd.Series:
    """Trailing beta = cov(name, market)/var(market) over a rolling window."""
    mp = min_periods or max(10, win // 2)
    cov = name_ret.rolling(win, min_periods=mp).cov(mkt_ret)
    varr = mkt_ret.rolling(win, min_periods=mp).var(ddof=0)
    return cov / varr.replace(0, np.nan)


def _market_period_returns(market: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample the daily S&P500 level to per-period returns.

    Returns a DataFrame keyed by (period label) with the market's period
    return, so each ticker row can align market returns to its own close
    period without lookahead (only closes through the period belong to it).
    """
    s = market[["date", "spx"]].dropna(subset=["spx"]).copy()
    s["date"] = pd.to_datetime(s["date"])
    s = s.sort_values("date")
    # label each daily obs with its period bucket, as in _period_end_dates
    if freq == "daily":
        s["label"] = s["date"]
    elif freq == "weekly":
        s["label"] = s["date"] - pd.to_timedelta(s["date"].dt.weekday, unit="D")
    elif freq == "monthly":
        s["label"] = s["date"].dt.to_period("M").dt.start_time.dt.normalize()
    else:  # quarterly
        s["label"] = s["date"].dt.to_period("Q").dt.start_time.dt.normalize()

    # period close = last trading day's spx level in the bucket
    per = s.groupby("label")["spx"].last().sort_index().pct_change().rename("mkt_ret")
    return per.reset_index()


def _add_rolling_stats(df: pd.DataFrame, market: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Compute trailing return-distribution + beta features per ticker.

    Runs on the per-grain close series AFTER the base/derived features are in
    the frame, so each row carries only its own history through the period-end
    close — PIT-correct, mirroring return_3m / max_drawdown_252.

    Distribution stats come from the name's own period returns; beta is the
    rolling cov/var of the name vs the S&P500 period return (aligned on the
    same period bucket, so there is no lookahead).
    """
    ppy = {"weekly": 52, "monthly": 12, "daily": 252, "quarterly": 4}[freq]
    win = ROLLING_RET_WINDOW.get(freq, 12)
    bwin = ROLLING_BETA_WINDOW.get(freq, 24)

    d = df.copy().sort_values(["ticker", "date"]).reset_index(drop=True)
    d["_ret"] = d.groupby("ticker")["close"].pct_change()

    # per-period market returns aligned to the same period bucket
    mkt = _market_period_returns(market, freq)
    if freq == "daily":
        d["_label"] = d["date"]
    elif freq == "weekly":
        d["_label"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
    elif freq == "monthly":
        d["_label"] = d["date"].dt.to_period("M").dt.start_time.dt.normalize()
    else:
        d["_label"] = d["date"].dt.to_period("Q").dt.start_time.dt.normalize()
    d = d.merge(mkt, left_on="_label", right_on="label", how="left")

    for col, fn in {
        "roll_sharpe": lambda r: _rolling_sharpe(r, win, ppy),
        "roll_skew": lambda r: _rolling_skew(r, win),
        "roll_kurt": lambda r: _rolling_kurt(r, win),
        "roll_downside_dev": lambda r: _rolling_downside_dev(r, win),
        "roll_var95": lambda r: _rolling_var95(r, win),
    }.items():
        buf = np.full(len(d), np.nan)
        for _, sub in d.groupby("ticker"):
            buf[sub.index] = fn(sub["_ret"]).to_numpy()
        d[col] = buf

    buf = np.full(len(d), np.nan)
    for _, sub in d.groupby("ticker"):
        buf[sub.index] = _rolling_beta(sub["_ret"], sub["mkt_ret"], bwin).to_numpy()
    d["roll_beta"] = buf

    d = d.drop(columns=["_ret", "_label", "label", "mkt_ret"])
    return d


# ── Target variable ─────────────────────────────────────────────────────────────


def _add_target(
    df: pd.DataFrame, freq: str = "monthly", last_trade: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Add next-period return as the prediction target.

    For the quarterly grain, a target is only valid when the *forward* quarter
    is fully closed in the warehouse (its last trading day is observable).
    Difference between the mart's period-start label and the real trade date is
    why this compares against `staging.stg_prices_daily` max dates rather than
    the label itself — otherwise an in-progress quarter (which always has some
    bars) would look complete. Marginal ~5 business days at quarter-end are
    treated as closed to absorb holidays/weekends.
    """
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    df["target_return"] = g["close"].shift(-1) / df["close"] - 1
    if freq == "quarterly" and last_trade is not None:
        # The target spans the NEXT quarter, so that quarter must be closed
        # (label is the period start: +2 quarter-ends = forward quarter end).
        fwd_end = (df["date"] + pd.offsets.QuarterEnd(2)).dt.normalize()
        lt = df[["ticker"]].merge(last_trade, on="ticker", how="left")
        closed = pd.to_datetime(lt["last_date"]) >= (fwd_end - pd.Timedelta(days=5))
        # ...and the next row must actually be the adjacent quarter, not a
        # later one after a data gap.
        adjacent = g["date"].shift(-1) == df["date"] + pd.DateOffset(months=3)
        df.loc[~(closed & adjacent), "target_return"] = np.nan
    return df


def last_closed_week(newest_trade, now=None) -> pd.Timestamp:
    """Monday label of the newest week whose Friday session has closed.

    Decided by the clock, not by spotting a Friday bar: a holiday Friday
    (Good Friday, July 4th) still closes its week at 16:00 ET, while a run
    on Wednesday must not treat the half-finished week as done. `newest_trade`
    is the latest bar date in the warehouse.
    """
    now = pd.Timestamp.now(tz=MARKET_TZ) if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    now = now.tz_convert(MARKET_TZ)
    newest = pd.Timestamp(newest_trade).normalize()
    week = newest - pd.Timedelta(days=newest.weekday())
    friday_close = (week + pd.Timedelta(days=4, hours=16)).tz_localize(MARKET_TZ)
    return week if now >= friday_close else week - pd.Timedelta(weeks=1)


def _add_weekly_targets(df: pd.DataFrame, closed_through: pd.Timestamp) -> pd.DataFrame:
    """Forward returns for each WEEKLY_HORIZONS column, entered at next week's open.

    A row's h-week target is close(week + h) / open(week + 1) - 1. It is only
    set when weeks +1 and +h are the adjacent rows (no data gap) and week +h
    has closed (`closed_through`); otherwise NaN, i.e. not yet known.
    """
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    entry = g["open"].shift(-1)
    entry_ok = g["date"].shift(-1) == df["date"] + pd.Timedelta(weeks=1)
    for col, h in WEEKLY_HORIZONS.items():
        exit_week = df["date"] + pd.Timedelta(weeks=h)
        ok = entry_ok & (g["date"].shift(-h) == exit_week) & (exit_week <= closed_through)
        df[col] = np.where(ok, g["close"].shift(-h) / entry - 1, np.nan)
    return df


# ── Main ────────────────────────────────────────────────────────────────────────


def build_dataset(
    freq: str = "monthly", tickers: list[str] | None = None, keep_unlabeled: bool = False, now=None
) -> pd.DataFrame:
    """Build the full training dataset for one bar frequency.

    `tickers` restricts every load to the curated training universe; None
    falls back to TRAIN_TICKERS, then to every ticker in the warehouse.
    `keep_unlabeled` keeps rows whose target isn't known yet (the latest
    period) so the caller can score the live cohort; training must still
    drop them. `now` (weekly only) is the clock that decides which weeks have
    closed; None = the current time.
    """
    wh = Warehouse()

    if tickers is None:
        tickers = TRAIN_TICKERS
    n_ticker = len(tickers) if tickers else "ALL"
    print(f"Training universe: {n_ticker} ticker(s)\n")

    # Quarterly uses its own feature set (macro momentum + fundamental
    # velocity); weekly adds quarterly-scale momentum and short-horizon
    # signals to the 14-day indicator set; monthly/daily keep the latter.
    if freq == "quarterly":
        ti_cols, aa_cols, fund_cols = (
            QUARTERLY_TI_FEATURES,
            QUARTERLY_AA_FEATURES,
            QUARTERLY_FUND_FEATURES,
        )
    elif freq == "weekly":
        ti_cols, aa_cols, fund_cols = (WEEKLY_TI_FEATURES, WEEKLY_AA_FEATURES, FUNDAMENTAL_FEATURES)
    else:
        ti_cols, aa_cols, fund_cols = TI_FEATURES, AA_FEATURES, FUNDAMENTAL_FEATURES

    print(f"Loading price ({freq})...")
    anchor = _load_price(wh, freq, tickers)
    print(f"  {len(anchor)} rows, {anchor['ticker'].nunique()} tickers")

    print("Loading technical indicators...")
    ti = _load_technical_indicators(wh, ti_cols, tickers)
    print(f"  {len(ti)} daily rows")

    print("Loading advanced analytics...")
    aa = _load_advanced_analytics(wh, aa_cols, tickers)
    print(f"  {len(aa)} daily rows")

    print("Loading financials...")
    fins = _load_financials(wh, tickers)
    print(f"  {len(fins)} quarterly reports, {fins['ticker'].nunique()} tickers")

    print("Loading company profiles (sector)...")
    profiles = _load_company_profile(wh, tickers)
    print(f"  {len(profiles)} tickers")

    print("Loading market series (VIX / S&P 500)...")
    market = _load_market(wh)
    print(
        f"  {len(market)} daily rows, {market['date'].min().date()} → {market['date'].max().date()}"
    )

    print("Computing period-end snapshot dates...")
    asof = _period_end_dates(ti, freq)
    anchor = anchor.merge(asof, on=["ticker", "date"], how="left")

    print("Snapshotting daily → period (technical indicators)...")
    ti_anchor = _snapshot_daily(ti, anchor, ti_cols)

    print("Snapshotting daily → period (advanced analytics)...")
    aa_anchor = _snapshot_daily(aa, anchor, aa_cols)

    # Merge: anchor base + TI + AA
    print("Merging features...")
    dataset = anchor[["ticker", "date", "open", "high", "low", "close", "volume"]].copy()
    dataset = dataset.merge(ti_anchor, on=["ticker", "date"], how="left")
    dataset = dataset.merge(aa_anchor, on=["ticker", "date"], how="left")

    # PIT fundamentals
    print("Joining PIT fundamentals...")
    dataset = _pit_join_fundamentals(dataset, fins, fund_cols)

    # Static sector label (per ticker, not per period)
    print("Joining sector labels...")
    dataset = dataset.merge(profiles, on="ticker", how="left")

    # Re-cast numeric columns (merge can introduce object dtypes)
    for col in (
        ["open", "high", "low", "close", "volume"] + ti_cols + aa_cols + fund_cols + MARKET_FEATURES
    ):
        if col in dataset.columns:
            dataset[col] = pd.to_numeric(dataset[col], errors="coerce")

    # Market regime as-of period-end (VIX + S&P500), PIT
    print("Joining market features (as-of)...")
    dataset = _merge_market(dataset, market, asof)

    # Derived features
    print("Computing derived features...")
    if freq == "quarterly":
        dataset = _add_quarterly_features(dataset)
        feat_names = QUARTERLY_ALL_FEATURES
    elif freq == "weekly":
        dataset = _add_weekly_features(_add_derived_features(dataset))
        feat_names = WEEKLY_ALL_FEATURES
    else:
        dataset = _add_derived_features(dataset)
        feat_names = ALL_FEATURES

    # Rolling return-distribution statistics + beta (PIT, per ticker)
    print("Computing rolling stats & beta...")
    dataset = _add_rolling_stats(dataset, market, freq)

    # S&P 500 membership on each snapshot day (point in time)
    print("Flagging S&P 500 membership (point in time)...")
    membership = _load_sp500_membership(wh)
    snap = dataset[["ticker", "date"]].merge(asof, on=["ticker", "date"], how="left")
    snap["asof"] = pd.to_datetime(snap["asof_date"]).fillna(snap["date"])
    flags = _index_membership(snap.set_index(dataset.index), membership)
    dataset[["in_index", "sp500_status"]] = flags[["in_index", "sp500_status"]]
    if membership.empty:
        print("  WARNING: no S&P 500 membership staged; every row counts (survivors included)")
    else:
        statuses = dataset.drop_duplicates("ticker")["sp500_status"].value_counts().to_dict()
        print(
            f"  {int(dataset['in_index'].sum())} of {len(dataset)} rows in the index; "
            f"tickers by status {statuses}"
        )

    # Target
    print("Adding target variable...")
    if freq in ("quarterly", "weekly"):
        with wh.connect(read_only=True) as con:
            last_trade = pd.read_sql(
                "SELECT ticker, MAX(date) AS last_date "
                "FROM staging.stg_prices_daily GROUP BY ticker",
                con,
            )
    else:
        last_trade = None
    if freq == "weekly":
        closed = last_closed_week(pd.to_datetime(last_trade["last_date"]).max(), now)
        print(f"  weeks closed through {closed.date()}")
        dataset = _add_weekly_targets(dataset, closed)
    else:
        dataset = _add_target(dataset, freq, last_trade)

    # Drop rows with no target (last period per ticker)
    if not keep_unlabeled:
        dataset = dataset.dropna(subset=["target_return"])

    print(f"\nDataset: {len(dataset)} rows, {dataset['ticker'].nunique()} tickers")
    print(f"Date range: {dataset['date'].min()} → {dataset['date'].max()}")
    print(
        f"Features: {len(feat_names)} base + derived "
        f"+ {len(CATEGORICAL_FEATURES)} categorical ({', '.join(CATEGORICAL_FEATURES)})"
    )
    missing = dataset["sector"].isna().sum()
    if missing:
        print(f"WARNING: {missing} rows with missing sector")

    return dataset


if __name__ == "__main__":
    import argparse

    def _split_tickers(arg: str) -> list[str]:
        return [t.strip() for t in arg.split(",") if t.strip()]

    parser = argparse.ArgumentParser(description="Build the ML training dataset.")
    parser.add_argument(
        "--freq",
        choices=["daily", "weekly", "monthly", "quarterly"],
        default="monthly",
        help="bar frequency of the dataset (default: monthly)",
    )
    parser.add_argument(
        "--tickers",
        type=_split_tickers,
        default=None,
        help="comma-separated training universe, e.g. 'AAPL,MSFT,NVDA' "
        "(overrides TRAIN_TICKERS constant)",
    )
    parser.add_argument(
        "--tickers-file",
        type=Path,
        default=None,
        help="path to a newline- or comma-separated ticker list for the "
        "training universe (overrides TRAIN_TICKERS constant)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output parquet path (default: train_dataset[_freq].parquet in Model/datasets/)",
    )
    args = parser.parse_args()

    tickers = None
    if args.tickers and args.tickers_file:
        parser.error("provide either --tickers or --tickers-file, not both")
    if args.tickers_file:
        tickers = [
            t.strip()
            for t in args.tickers_file.read_text().replace(",", "\n").splitlines()
            if t.strip()
        ]
    elif args.tickers:
        tickers = args.tickers

    dataset = build_dataset(freq=args.freq, tickers=tickers)
    default_names = {
        "daily": "train_dataset.parquet",
        "weekly": "train_dataset_weekly.parquet",
        "monthly": "train_dataset_monthly.parquet",
        "quarterly": "train_dataset_quarterly.parquet",
    }
    out_path = args.out or (
        Path(__file__).resolve().parent.parent / "datasets" / default_names[args.freq]
    )
    dataset.to_parquet(out_path, index=False)
    print(f"\nSaved to {out_path}")
