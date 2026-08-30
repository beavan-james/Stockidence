"""Build the ML training dataset.

For each (ticker, month-end), assembles:
  - Price-derived features from m_technical_indicators (daily → month-end snapshot)
  - Rolling analytics from m_advanced_analytics (daily → month-end snapshot)
  - PIT fundamentals from raw_financials_reported (latest available quarterly report)
  - Target: next-month return (monthly close-to-close)

Output: Model/train_dataset.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stockidence.storage import Warehouse


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

# Derived from raw_financials_reported (PIT)
FUNDAMENTAL_FEATURES = [
    "roe",           # net_income / equity
    "roa",           # net_income / assets
    "debt_equity",   # liabilities / equity
    "current_ratio", # current_assets / current_liabilities
    "cash_to_assets",# cash / total_assets
    "fcf",           # operating cash flow - capex
]

ALL_FEATURES = TI_FEATURES + AA_FEATURES + FUNDAMENTAL_FEATURES


# ── Data loading helpers ────────────────────────────────────────────────────────

def _load_price_monthly(wh: Warehouse) -> pd.DataFrame:
    """Load monthly OHLCV bars."""
    with wh.connect(read_only=True) as con:
        df = pd.read_sql(
            "SELECT ticker, date, open, high, low, close, volume "
            "FROM mart.m_prices_monthly ORDER BY ticker, date",
            con,
        )
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_technical_indicators(wh: Warehouse) -> pd.DataFrame:
    """Load daily technical indicators."""
    with wh.connect(read_only=True) as con:
        cols = ["ticker", "date"] + TI_FEATURES
        sql = f"SELECT {', '.join(cols)} FROM mart.m_technical_indicators ORDER BY ticker, date"
        df = pd.read_sql(sql, con)
    df["date"] = pd.to_datetime(df["date"])
    for col in TI_FEATURES:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_advanced_analytics(wh: Warehouse) -> pd.DataFrame:
    """Load daily advanced analytics."""
    with wh.connect(read_only=True) as con:
        cols = ["ticker", "date", "close"] + AA_FEATURES
        sql = f"SELECT {', '.join(cols)} FROM mart.m_advanced_analytics ORDER BY ticker, date"
        df = pd.read_sql(sql, con)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["close"] + AA_FEATURES:
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

    records = []
    for ticker, year, quarter, payload_str in rows:
        payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        report = payload.get("report", {})
        bs = {item["concept"]: item.get("value") for item in report.get("bs", [])}
        cf = {item["concept"]: item.get("value") for item in report.get("cf", [])}

        def _get(d: dict, key: str) -> float | None:
            v = d.get(key)
            return float(v) if v is not None else None

        total_assets = _get(bs, "us-gaap_Assets")
        liabilities = _get(bs, "us-gaap_Liabilities")
        equity = _get(bs, "us-gaap_StockholdersEquity")
        current_assets = _get(bs, "us-gaap_AssetsCurrent")
        current_liabilities = _get(bs, "us-gaap_LiabilitiesCurrent")
        cash = _get(bs, "us-gaap_CashAndCashEquivalentsAtCarryingValue")
        net_income = _get(cf, "us-gaap_NetIncomeLoss")
        ocf = _get(cf, "us-gaap_NetCashProvidedByUsedInOperatingActivities")
        capex = _get(cf, "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment")

        roe = net_income / equity if net_income and equity and equity > 0 else None
        roa = net_income / total_assets if net_income and total_assets and total_assets > 0 else None
        debt_equity = liabilities / equity if liabilities and equity and equity > 0 else None
        current_ratio = current_assets / current_liabilities if current_assets and current_liabilities and current_liabilities > 0 else None
        cash_to_assets = cash / total_assets if cash and total_assets and total_assets > 0 else None
        fcf = (ocf - capex) if ocf is not None and capex is not None else None

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
            "fcf": fcf,
        })

    return pd.DataFrame(records)


# ── PIT join logic ──────────────────────────────────────────────────────────────

def _pit_join_fundamentals(
    monthly: pd.DataFrame,
    financials: pd.DataFrame,
) -> pd.DataFrame:
    """For each (ticker, month-end), attach the latest quarterly report
    whose filed_date <= month-end (point-in-time correct)."""
    if financials.empty:
        for col in FUNDAMENTAL_FEATURES:
            monthly[col] = np.nan
        return monthly

    financials = financials.dropna(subset=["filed_date"]).copy()
    financials = financials.sort_values(["ticker", "filed_date"])

    # Use merge_asof: for each monthly row, find the latest filing <= month-end
    fin_cols = ["ticker", "filed_date"] + FUNDAMENTAL_FEATURES
    result = pd.merge_asof(
        monthly.sort_values("date"),
        financials[fin_cols].rename(columns={"filed_date": "date"}).sort_values("date"),
        on="date",
        by="ticker",
        direction="backward",
    )
    return result


# ── Feature engineering ──────────────────────────────────────────────────────────

def _snapshot_daily_to_monthly(
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    feature_cols: list[str],
) -> pd.DataFrame:
    """For each (ticker, month-end date), grab the latest daily row."""
    daily = daily.sort_values(["ticker", "date"])
    month_keys = monthly[["ticker", "date"]].drop_duplicates().sort_values("date")

    result = pd.merge_asof(
        month_keys,
        daily[["ticker", "date"] + feature_cols].sort_values("date"),
        on="date",
        by="ticker",
        direction="backward",
    )
    return result


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
        df["dist_from_52w_high"] = np.where(range_52w != 0, (df["close"] - df["max_252"]) / range_52w, np.nan)
        df["dist_from_52w_low"] = np.where(range_52w != 0, (df["close"] - df["min_252"]) / range_52w, np.nan)

    # ATR normalized by price (volatility proxy)
    if "atr_14" in df.columns:
        df["atr_pct"] = df["atr_14"] / df["close"]

    # Volatility ratio (stddev / mean — normalized volatility)
    if "stddev_252" in df.columns and "mean_252" in df.columns:
        df["vol_ratio"] = np.where(df["mean_252"] != 0, df["stddev_252"] / df["mean_252"], np.nan)

    # FCF yield (FCF / close — needs shares outstanding, approximate with close)
    if "fcf" in df.columns:
        df["fcf_yield"] = np.where(df["close"] != 0, df["fcf"] / df["close"], np.nan)

    return df


# ── Target variable ─────────────────────────────────────────────────────────────

def _add_target(df: pd.DataFrame) -> pd.DataFrame:
    """Add next-month return as the prediction target."""
    df = df.sort_values(["ticker", "date"])
    df["target_return"] = df.groupby("ticker")["close"].pct_change().shift(-1)
    return df


# ── Main ────────────────────────────────────────────────────────────────────────

def build_dataset() -> pd.DataFrame:
    """Build the full training dataset."""
    wh = Warehouse()

    print("Loading price monthly...")
    monthly = _load_price_monthly(wh)
    print(f"  {len(monthly)} rows, {monthly['ticker'].nunique()} tickers")

    print("Loading technical indicators...")
    ti = _load_technical_indicators(wh)
    print(f"  {len(ti)} daily rows")

    print("Loading advanced analytics...")
    aa = _load_advanced_analytics(wh)
    print(f"  {len(aa)} daily rows")

    print("Loading financials...")
    fins = _load_financials(wh)
    print(f"  {len(fins)} quarterly reports, {fins['ticker'].nunique()} tickers")

    print("Snapshotting daily → monthly (technical indicators)...")
    ti_monthly = _snapshot_daily_to_monthly(ti, monthly, TI_FEATURES)

    print("Snapshotting daily → monthly (advanced analytics)...")
    aa_monthly = _snapshot_daily_to_monthly(aa, monthly, AA_FEATURES + ["close"])

    # Merge: monthly base + TI + AA
    print("Merging features...")
    dataset = monthly[["ticker", "date", "open", "high", "low", "close", "volume"]].copy()
    ti_cols = ["ticker", "date"] + TI_FEATURES
    aa_cols = ["ticker", "date"] + AA_FEATURES
    dataset = dataset.merge(ti_monthly[ti_cols], on=["ticker", "date"], how="left")
    dataset = dataset.merge(aa_monthly[aa_cols], on=["ticker", "date"], how="left")

    # PIT fundamentals
    print("Joining PIT fundamentals...")
    dataset = _pit_join_fundamentals(dataset, fins)

    # Re-cast numeric columns (merge can introduce object dtypes)
    for col in ["open", "high", "low", "close", "volume"] + TI_FEATURES + AA_FEATURES + FUNDAMENTAL_FEATURES:
        if col in dataset.columns:
            dataset[col] = pd.to_numeric(dataset[col], errors="coerce")

    # Derived features
    print("Computing derived features...")
    dataset = _add_derived_features(dataset)

    # Target
    print("Adding target variable...")
    dataset = _add_target(dataset)

    # Drop rows with no target (last month per ticker)
    dataset = dataset.dropna(subset=["target_return"])

    print(f"\nDataset: {len(dataset)} rows, {dataset['ticker'].nunique()} tickers")
    print(f"Date range: {dataset['date'].min()} → {dataset['date'].max()}")
    print(f"Features: {len(ALL_FEATURES)} base + derived")

    return dataset


if __name__ == "__main__":
    dataset = build_dataset()
    out_path = Path(__file__).parent / "train_dataset.parquet"
    dataset.to_parquet(out_path, index=False)
    print(f"\nSaved to {out_path}")
