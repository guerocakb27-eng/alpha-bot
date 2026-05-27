"""Volume indicators: Volume SMA, OBV, CMF, MFI, AD line, Force Index, RVOL,
PVT, Volume Profile, VWMA."""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.volume import (
    AccDistIndexIndicator,
    ChaikinMoneyFlowIndicator,
    ForceIndexIndicator,
    MFIIndicator,
    OnBalanceVolumeIndicator,
    VolumePriceTrendIndicator,
)


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["volume"].rolling(period).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    return OnBalanceVolumeIndicator(df["close"], df["volume"], fillna=False).on_balance_volume()


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return ChaikinMoneyFlowIndicator(
        df["high"], df["low"], df["close"], df["volume"], window=period, fillna=False
    ).chaikin_money_flow()


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return MFIIndicator(
        df["high"], df["low"], df["close"], df["volume"], window=period, fillna=False
    ).money_flow_index()


def ad_line(df: pd.DataFrame) -> pd.Series:
    return AccDistIndexIndicator(df["high"], df["low"], df["close"], df["volume"], fillna=False).acc_dist_index()


def force_index(df: pd.DataFrame, period: int = 13) -> pd.Series:
    return ForceIndexIndicator(df["close"], df["volume"], window=period, fillna=False).force_index()


def rvol(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Relative volume: current / rolling mean."""
    return df["volume"] / df["volume"].rolling(period).mean()


def pvt(df: pd.DataFrame) -> pd.Series:
    return VolumePriceTrendIndicator(df["close"], df["volume"], fillna=False).volume_price_trend()


def volume_profile(df: pd.DataFrame, bins: int = 20) -> dict[str, float]:
    """Discretize price range into bins; total volume per bin.

    Returns Point Of Control (price of highest-volume bin) plus Value Area
    (smallest contiguous range covering 70% of volume).
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    hist, edges = np.histogram(typical, bins=bins, weights=df["volume"])
    centers = (edges[:-1] + edges[1:]) / 2

    poc_idx = int(np.argmax(hist))
    poc = float(centers[poc_idx])

    total = hist.sum()
    target = total * 0.70
    lo, hi = poc_idx, poc_idx
    acc = hist[poc_idx]
    while acc < target and (lo > 0 or hi < bins - 1):
        left = hist[lo - 1] if lo > 0 else -1
        right = hist[hi + 1] if hi < bins - 1 else -1
        if left >= right:
            lo -= 1
            acc += left
        else:
            hi += 1
            acc += right

    return {
        "poc": poc,
        "value_area_high": float(centers[hi]),
        "value_area_low": float(centers[lo]),
    }


def vwma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    pv = df["close"] * df["volume"]
    return pv.rolling(period).sum() / df["volume"].rolling(period).sum()
