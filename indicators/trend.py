"""Trend indicators: EMA, SMA, WMA, DEMA, TEMA, HMA, VWAP, Ichimoku, PSAR,
Supertrend, Linear Regression, ADX."""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.trend import (
    ADXIndicator,
    EMAIndicator,
    IchimokuIndicator,
    PSARIndicator,
    SMAIndicator,
    WMAIndicator,
)
from ta.volume import VolumeWeightedAveragePrice


def ema(df: pd.DataFrame, periods: list[int] | None = None) -> dict[int, pd.Series]:
    periods = periods or [9, 21, 50, 100, 200]
    return {p: EMAIndicator(df["close"], window=p, fillna=False).ema_indicator() for p in periods}


def sma(df: pd.DataFrame, periods: list[int] | None = None) -> dict[int, pd.Series]:
    periods = periods or [20, 50, 200]
    return {p: SMAIndicator(df["close"], window=p, fillna=False).sma_indicator() for p in periods}


def wma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return WMAIndicator(df["close"], window=period, fillna=False).wma()


def dema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    e1 = df["close"].ewm(span=period, adjust=False).mean()
    e2 = e1.ewm(span=period, adjust=False).mean()
    return 2 * e1 - e2


def tema(df: pd.DataFrame, period: int = 20) -> pd.Series:
    e1 = df["close"].ewm(span=period, adjust=False).mean()
    e2 = e1.ewm(span=period, adjust=False).mean()
    e3 = e2.ewm(span=period, adjust=False).mean()
    return 3 * e1 - 3 * e2 + e3


def hma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    half = max(int(period / 2), 1)
    sqrt_p = max(int(np.sqrt(period)), 1)
    wma_half = WMAIndicator(df["close"], window=half).wma()
    wma_full = WMAIndicator(df["close"], window=period).wma()
    raw = 2 * wma_half - wma_full
    return WMAIndicator(raw.dropna(), window=sqrt_p).wma().reindex(df.index)


def vwap(df: pd.DataFrame) -> pd.Series:
    return VolumeWeightedAveragePrice(
        high=df["high"], low=df["low"], close=df["close"], volume=df["volume"], window=14
    ).volume_weighted_average_price()


def ichimoku(df: pd.DataFrame) -> dict[str, pd.Series]:
    ind = IchimokuIndicator(df["high"], df["low"], window1=9, window2=26, window3=52, fillna=False)
    tenkan = ind.ichimoku_conversion_line()
    kijun = ind.ichimoku_base_line()
    senkou_a = ind.ichimoku_a()
    senkou_b = ind.ichimoku_b()
    chikou = df["close"].shift(-26)
    return {"tenkan": tenkan, "kijun": kijun, "senkou_a": senkou_a, "senkou_b": senkou_b, "chikou": chikou}


def parabolic_sar(df: pd.DataFrame, af: float = 0.02, max_af: float = 0.2) -> pd.Series:
    return PSARIndicator(
        df["high"], df["low"], df["close"], step=af, max_step=max_af, fillna=False
    ).psar()


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> dict[str, pd.Series]:
    """Manual Supertrend (not in `ta` library).

    Returns dict with 'line' (the trend line) and 'direction' (+1 up, -1 down).
    """
    hl2 = (df["high"] + df["low"]) / 2
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_ = tr.rolling(period).mean()

    upper = hl2 + multiplier * atr_
    lower = hl2 - multiplier * atr_

    line = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=float)
    line.iloc[0] = upper.iloc[0]
    direction.iloc[0] = -1

    for i in range(1, len(df)):
        prev_line = line.iloc[i - 1]
        prev_dir = direction.iloc[i - 1]
        close = df["close"].iloc[i]

        if prev_dir == 1:
            new_line = max(lower.iloc[i], prev_line)
            new_dir = -1 if close < new_line else 1
        else:
            new_line = min(upper.iloc[i], prev_line)
            new_dir = 1 if close > new_line else -1
        # flip
        if new_dir != prev_dir:
            new_line = lower.iloc[i] if new_dir == 1 else upper.iloc[i]
        line.iloc[i] = new_line
        direction.iloc[i] = new_dir

    return {"line": line, "direction": direction}


def linear_regression(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    """Rolling linear regression value (LSMA) and slope."""
    close = df["close"].values
    n = len(close)
    val = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    x = np.arange(period)
    for i in range(period - 1, n):
        y = close[i - period + 1 : i + 1]
        m, b = np.polyfit(x, y, 1)
        val[i] = m * (period - 1) + b
        slope[i] = m
    return {"value": pd.Series(val, index=df.index), "slope": pd.Series(slope, index=df.index)}


def adx(df: pd.DataFrame, period: int = 14) -> dict[str, pd.Series]:
    ind = ADXIndicator(df["high"], df["low"], df["close"], window=period, fillna=False)
    return {"adx": ind.adx(), "plus_di": ind.adx_pos(), "minus_di": ind.adx_neg()}
