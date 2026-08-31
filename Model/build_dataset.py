"""Build the ML training dataset, parameterized by bar frequency.

For each (ticker, period label), assembles:
  - Price-derived features from m_technical_indicators (daily snapshot as-of
    the period's last trading day — the same day the anchor close is known)
  - Rolling analytics from m_advanced_analytics (same snapshot semantics)
  - PIT fundamentals from raw_financials_reported (latest available quarterly report)
  - Static sector label from raw_company_profile
  - Target: next-period return (anchor close-to-close)

Mart bars are labeled at period START (date_trunc) but hold the period-END
close (last(close)), so features are snapshotted on the period's last trading
day, never on the label itself — that keeps features and close on the same day
without lookahead.

Feature sets are frequency-specific:
  - weekly/monthly: 14-day technical indicators + the 6 static fundamentals
  - quarterly: macro momentum (price_to_sma200, return_3m/12m, 52wk-high
    distance, atr_pct, 252-day vol & drawdown) + fundamental velocity
    (static ratios plus their quarter-over-quarter change)

Grains: monthly (default), weekly, quarterly.
Output: Model/train_dataset.parquet (monthly) / train_dataset_{freq}.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from stockidence.storage import Warehouse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Feature constants ──────────────────────────────────────────────────────────

# From m_technical_indicators (month-end snapshot)
TI_FEATURES = [
    "sma_20", "sma_50", "sma_200",
    "ema_12", "ema_26",
    "rsi_14", "adx_14",
    "atr_14",
    "macd_hist",
    "stoch_k_14", "stoch_d_14",
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
    "vix", "vix_pctile_252", "vix_chg_21d",
    "spx_ret_21d", "spx_ret_63d", "spx_ret_252d",
]

# Derived from raw_financials_reported (PIT)
FUNDAMENTAL_FEATURES = [
    "roe",           # net_income / equity
    "roa",           # net_income / assets
    "debt_equity",   # liabilities / equity
    "current_ratio",  # current_assets / current_liabilities
    "cash_to_assets",  # cash / total_assets
    "fcf_to_assets",  # (ocf - capex) / total_assets
]

ALL_FEATURES = TI_FEATURES + AA_FEATURES + \
    FUNDAMENTAL_FEATURES + MARKET_FEATURES

# ── Quarterly-specific feature set ─────────────────────────────────────────────
# The quarterly dataset uses macro-scale momentum + fundamental velocity instead
# of 14-day indicators, which are a poor match for a ~3-month target window.
QUARTERLY_TI_FEATURES = [
    "sma_200",        # trend context for price_to_sma200
    "atr_14",         # input to atr_pct
]
QUARTERLY_AA_FEATURES = [
    "stddev_252",         # 252-day realized vol (structural context)
    "max_drawdown_252",   # deepest trailing drawdown
    "max_252",            # 52-week high (input to distance_from_52wk_high)
]

# Static fundamentals + quarter-over-quarter change (velocity). Trees see
# "ROE rose from 5% to 15%" rather than just a static level.
CHG_FEATURES = ["roe", "roa", "fcf_to_assets", "debt_equity"]
QUARTERLY_FUND_FEATURES = FUNDAMENTAL_FEATURES + \
    [f"{c}_chg_qoq" for c in CHG_FEATURES]

QUARTERLY_PRICE_FEATURES = [
    "price_to_sma200", "stddev_252", "max_drawdown_252", "atr_pct",
    "return_3m", "return_12m", "distance_from_52wk_high",
]
QUARTERLY_ALL_FEATURES = QUARTERLY_PRICE_FEATURES + \
    QUARTERLY_FUND_FEATURES + MARKET_FEATURES

# Categorical features are merged per ticker (not snapshot per period).
CATEGORICAL_FEATURES = ["sector"]

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

def _load_price(wh: Warehouse, freq: str = "monthly") -> pd.DataFrame:
    """Load anchor OHLCV bars labeled at period start (mart convention).

    Weekly/monthly come straight from the mart; quarterly is resampled from
    the monthly bars (close = last month's end-of-month close).
    """
    if freq in ("weekly", "monthly"):
        table = f"mart.m_prices_{freq}"
        with wh.connect(read_only=True) as con:
            df = pd.read_sql(
                f"SELECT ticker, date, open, high, low, close, volume "
                f"FROM {table} ORDER BY ticker, date",
                con,
            )
    elif freq == "quarterly":
        with wh.connect(read_only=True) as con:
            base = pd.read_sql(
                "SELECT ticker, date, open, high, low, close, volume "
                "FROM mart.m_prices_monthly ORDER BY ticker, date",
                con,
            )
        base["date"] = pd.to_datetime(base["date"])
        base["label"] = base["date"].dt.to_period(
            "Q").dt.start_time.dt.normalize()
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


def _load_technical_indicators(wh: Warehouse, feature_cols: list[str] | None = None) -> pd.DataFrame:
    """Load daily technical indicators."""
    cols = feature_cols if feature_cols is not None else TI_FEATURES
    with wh.connect(read_only=True) as con:
        sql_cols = ["ticker", "date"] + cols
        sql = f"SELECT {', '.join(sql_cols)} FROM mart.m_technical_indicators ORDER BY ticker, date"
        df = pd.read_sql(sql, con)
    df["date"] = pd.to_datetime(df["date"])
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_advanced_analytics(wh: Warehouse, feature_cols: list[str] | None = None) -> pd.DataFrame:
    """Load daily advanced analytics."""
    cols = feature_cols if feature_cols is not None else AA_FEATURES
    with wh.connect(read_only=True) as con:
        sql_cols = ["ticker", "date", "close"] + cols
        sql = f"SELECT {', '.join(sql_cols)} FROM mart.m_advanced_analytics ORDER BY ticker, date"
        df = pd.read_sql(sql, con)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["close"] + cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_financials(wh: Warehouse) -> pd.DataFrame:
    """Load PIT financials and extract key metrics from the payload JSON."""
    import json

    with wh.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT ticker, year, quarter, payload FROM raw.raw_financials_reported"
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
        payload = json.loads(payload_str) if isinstance(
            payload_str, str) else payload_str
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
                v = _to_float(concepts.get(key))
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
        roa = net_income / total_assets if net_income and total_assets and total_assets > 0 else None
        debt_equity = liabilities / equity if liabilities and equity and equity > 0 else None
        current_ratio = current_assets / \
            current_liabilities if current_assets and current_liabilities and current_liabilities > 0 else None
        cash_to_assets = cash / \
            total_assets if cash and total_assets and total_assets > 0 else None
        fcf = (ocf - capex) if ocf is not None and capex is not None else None
        fcf_to_assets = fcf / \
            total_assets if fcf is not None and total_assets and total_assets > 0 else None

        # Filing date determines PIT availability
        filed_date = payload.get("filedDate", "")
        end_date = payload.get("endDate", "")

        records.append({
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
        })

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
        m["vix"].rolling(252, min_periods=63)
        .apply(lambda w: (w <= w.iloc[-1]).mean(), raw=False)
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
        columns={"asof_date": "asof", "date": "label"})
    joined = pd.merge_asof(
        keys.sort_values("asof"),
        market.sort_values("date"),
        left_on="asof",
        right_on="date",
        direction="backward",
    )
    joined = joined[["ticker", "label"] +
                    MARKET_FEATURES].rename(columns={"label": "date"})
    return dataset.merge(joined, on=["ticker", "date"], how="left")


def _load_company_profile(wh: Warehouse) -> pd.DataFrame:
    """Load the coarse sector label per ticker from raw_company_profile.

    Finnhub classifies each company with a granular `finnhubIndustry`;
    SECTOR_MAP collapses that to ~11 GICS-like sectors. The label is
    Finnhub's *current* classification applied across all history —
    companies almost never change their industry, so no PIT handling.
    """
    import json

    with wh.connect(read_only=True) as con:
        rows = con.execute(
            "SELECT ticker, payload FROM raw.raw_company_profile"
        ).fetchall()

    records = []
    for ticker, payload_str in rows:
        payload = json.loads(payload_str) if isinstance(
            payload_str, str) else payload_str
        industry = payload.get("finnhubIndustry")
        records.append({"ticker": ticker, "sector": SECTOR_MAP.get(industry)})

    return pd.DataFrame(records)


# ── PIT join logic ──────────────────────────────────────────────────────────────

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
    financials["filed_date"] = pd.to_datetime(
        financials["filed_date"]).astype("datetime64[ns]")

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
    if freq == "weekly":
        d["label"] = d["date"] - pd.to_timedelta(
            d["date"].dt.weekday, unit="D")
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
    keys = anchor[["ticker", asof_col, "date"]].rename(
        columns={asof_col: "asof", "date": "label"})
    res = pd.merge_asof(
        keys.sort_values("asof"),
        daily[["ticker", "date"] + feature_cols].sort_values("date"),
        left_on="asof",
        right_on="date",
        by="ticker",
        direction="backward",
    )
    res = res[["ticker", "label"] +
              feature_cols].rename(columns={"label": "date"})
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
            range_52w != 0, (df["close"] - df["max_252"]) / range_52w, np.nan)
        df["dist_from_52w_low"] = np.where(
            range_52w != 0, (df["close"] - df["min_252"]) / range_52w, np.nan)

    # ATR normalized by price (volatility proxy)
    if "atr_14" in df.columns:
        df["atr_pct"] = df["atr_14"] / df["close"]

    # Volatility ratio (stddev / mean — normalized volatility)
    if "stddev_252" in df.columns and "mean_252" in df.columns:
        df["vol_ratio"] = np.where(
            df["mean_252"] != 0, df["stddev_252"] / df["mean_252"], np.nan)

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


# ── Target variable ─────────────────────────────────────────────────────────────

def _add_target(df: pd.DataFrame) -> pd.DataFrame:
    """Add next-month return as the prediction target."""
    df = df.sort_values(["ticker", "date"])
    df["target_return"] = df.groupby("ticker")["close"].pct_change().shift(-1)
    return df


# ── Main ────────────────────────────────────────────────────────────────────────

def build_dataset(freq: str = "monthly") -> pd.DataFrame:
    """Build the full training dataset for one bar frequency."""
    wh = Warehouse()

    # Quarterly uses its own feature set (macro momentum + fundamental
    # velocity); weekly/monthly keep the 14-day indicator set.
    if freq == "quarterly":
        ti_cols, aa_cols, fund_cols = (
            QUARTERLY_TI_FEATURES, QUARTERLY_AA_FEATURES, QUARTERLY_FUND_FEATURES)
    else:
        ti_cols, aa_cols, fund_cols = TI_FEATURES, AA_FEATURES, FUNDAMENTAL_FEATURES

    print(f"Loading price ({freq})...")
    anchor = _load_price(wh, freq)
    print(f"  {len(anchor)} rows, {anchor['ticker'].nunique()} tickers")

    print("Loading technical indicators...")
    ti = _load_technical_indicators(wh, ti_cols)
    print(f"  {len(ti)} daily rows")

    print("Loading advanced analytics...")
    aa = _load_advanced_analytics(wh, aa_cols)
    print(f"  {len(aa)} daily rows")

    print("Loading financials...")
    fins = _load_financials(wh)
    print(
        f"  {len(fins)} quarterly reports, {fins['ticker'].nunique()} tickers")

    print("Loading company profiles (sector)...")
    profiles = _load_company_profile(wh)
    print(f"  {len(profiles)} tickers")

    print("Loading market series (VIX / S&P 500)...")
    market = _load_market(wh)
    print(
        f"  {len(market)} daily rows, {market['date'].min().date()} → {market['date'].max().date()}")

    print("Computing period-end snapshot dates...")
    asof = _period_end_dates(ti, freq)
    anchor = anchor.merge(asof, on=["ticker", "date"], how="left")

    print("Snapshotting daily → period (technical indicators)...")
    ti_anchor = _snapshot_daily(ti, anchor, ti_cols)

    print("Snapshotting daily → period (advanced analytics)...")
    aa_anchor = _snapshot_daily(aa, anchor, aa_cols)

    # Merge: anchor base + TI + AA
    print("Merging features...")
    dataset = anchor[["ticker", "date", "open",
                      "high", "low", "close", "volume"]].copy()
    dataset = dataset.merge(ti_anchor, on=["ticker", "date"], how="left")
    dataset = dataset.merge(aa_anchor, on=["ticker", "date"], how="left")

    # PIT fundamentals
    print("Joining PIT fundamentals...")
    dataset = _pit_join_fundamentals(dataset, fins, fund_cols)

    # Static sector label (per ticker, not per period)
    print("Joining sector labels...")
    dataset = dataset.merge(profiles, on="ticker", how="left")

    # Re-cast numeric columns (merge can introduce object dtypes)
    for col in ["open", "high", "low", "close", "volume"] + ti_cols + aa_cols + fund_cols + MARKET_FEATURES:
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
    else:
        dataset = _add_derived_features(dataset)
        feat_names = ALL_FEATURES

    # Target
    print("Adding target variable...")
    dataset = _add_target(dataset)

    # Drop rows with no target (last period per ticker)
    dataset = dataset.dropna(subset=["target_return"])

    print(
        f"\nDataset: {len(dataset)} rows, {dataset['ticker'].nunique()} tickers")
    print(f"Date range: {dataset['date'].min()} → {dataset['date'].max()}")
    print(f"Features: {len(feat_names)} base + derived "
          f"+ {len(CATEGORICAL_FEATURES)} categorical ({', '.join(CATEGORICAL_FEATURES)})")
    missing = dataset["sector"].isna().sum()
    if missing:
        print(f"WARNING: {missing} rows with missing sector")

    return dataset


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Build the ML training dataset.")
    parser.add_argument(
        "--freq",
        choices=["monthly", "weekly", "quarterly"],
        default="monthly",
        help="bar frequency of the dataset (default: monthly)",
    )
    args = parser.parse_args()

    dataset = build_dataset(freq=args.freq)
    out_path = Path(__file__).parent / (
        "train_dataset.parquet"
        if args.freq == "monthly"
        else f"train_dataset_{args.freq}.parquet"
    )
    dataset.to_parquet(out_path, index=False)
    print(f"\nSaved to {out_path}")
