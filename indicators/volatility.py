"""Volatility indicators: Bollinger, Keltner, ATR, Donchian, Std Dev,
Chaikin Volatility, Historical Volatility, BB Squeeze."""
from __future__ import annotations

import numpy as np
import pandas as pd
from ta.volatility import (
    AverageTrueRange,
    BollingerBands,
    DonchianChannel,
    KeltnerChannel,
)


def bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict[str, pd.Series]:
    ind = BollingerBands(df["close"], window=period, window_dev=std, fillna=False)
    upper = ind.bollinger_hband()
    middle = ind.bollinger_mavg()
    lower = ind.bollinger_lband()
    width = (upper - lower) / middle
    pb = (df["close"] - lower) / (upper - lower)
    return {"upper": upper, "middle": middle, "lower": lower, "width": width, "percent_b": pb}


def keltner_channel(df: pd.DataFrame, period: int = 20, multiplier: float = 1.5) -> dict[str, pd.Series]:
    ind = KeltnerChannel(
        df["high"], df["low"], df["close"], window=period, window_atr=10,
        fillna=False, original_version=False, multiplier=multiplier,
    )
    return {"upper": ind.keltner_channel_hband(), "middle": ind.keltner_channel_mband(), "lower": ind.keltner_channel_lband()}


def atr(df: pd.DataFrame, periods: list[int] | None = None) -> dict[int, pd.Series]:
    periods = periods or [7, 14]
    return {p: AverageTrueRange(df["high"], df["low"], df["close"], window=p, fillna=False).average_true_range() for p in periods}


def donchian_channel(df: pd.DataFrame, period: int = 20) -> dict[str, pd.Series]:
    ind = DonchianChannel(df["high"], df["low"], df["close"], window=period, fillna=False)
    return {"upper": ind.donchian_channel_hband(), "middle": ind.donchian_channel_mband(), "lower": ind.donchian_channel_lband()}


def standard_deviation(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return df["close"].rolling(period).std()


def chaikin_volatility(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """ROC of EMA of (high - low)."""
    hl = df["high"] - df["low"]
    ema_hl = hl.ewm(span=period, adjust=False).mean()
    return ((ema_hl - ema_hl.shift(period)) / ema_hl.shift(period)) * 100


def historical_volatility(df: pd.DataFrame, period: int = 30) -> pd.Series:
    """Annualized std of log returns (in %). Assumes 365 trading days for crypto."""
    log_ret = np.log(df["close"] / df["close"].shift(1))
    return log_ret.rolling(period).std() * np.sqrt(365) * 100


def bb_squeeze(df: pd.DataFrame, period: int = 20, bb_std: float = 2.0, kc_mult: float = 1.5) -> pd.Series:
    """True when Bollinger Bands are inside Keltner Channel (volatility compression)."""
    bb = bollinger_bands(df, period=period, std=bb_std)
    kc = keltner_channel(df, period=period, multiplier=kc_mult)
    return (bb["upper"] < kc["upper"]) & (bb["lower"] > kc["lower"])
