"""Momentum indicators: RSI, Stoch RSI, MACD, CCI, Williams %R, ROC, Momentum,
TSI, DPO, Awesome Oscillator, Ultimate Oscillator."""
from __future__ import annotations

import pandas as pd
from ta.momentum import (
    AwesomeOscillatorIndicator,
    ROCIndicator,
    RSIIndicator,
    StochRSIIndicator,
    TSIIndicator,
    UltimateOscillator,
    WilliamsRIndicator,
)
from ta.trend import CCIIndicator, DPOIndicator, MACD


def rsi(df: pd.DataFrame, periods: list[int] | None = None) -> dict[int, pd.Series]:
    periods = periods or [7, 14, 21]
    return {p: RSIIndicator(df["close"], window=p, fillna=False).rsi() for p in periods}


def stochastic_rsi(df: pd.DataFrame, period: int = 14, k: int = 3, d: int = 3) -> dict[str, pd.Series]:
    ind = StochRSIIndicator(df["close"], window=period, smooth1=k, smooth2=d, fillna=False)
    return {"k": ind.stochrsi_k() * 100, "d": ind.stochrsi_d() * 100}


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    ind = MACD(df["close"], window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
    return {"macd": ind.macd(), "signal": ind.macd_signal(), "histogram": ind.macd_diff()}


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return CCIIndicator(df["high"], df["low"], df["close"], window=period, fillna=False).cci()


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return WilliamsRIndicator(df["high"], df["low"], df["close"], lbp=period, fillna=False).williams_r()


def roc(df: pd.DataFrame, period: int = 10) -> pd.Series:
    return ROCIndicator(df["close"], window=period, fillna=False).roc()


def momentum(df: pd.DataFrame, period: int = 10) -> pd.Series:
    return df["close"] - df["close"].shift(period)


def tsi(df: pd.DataFrame, slow: int = 25, fast: int = 13) -> pd.Series:
    return TSIIndicator(df["close"], window_slow=slow, window_fast=fast, fillna=False).tsi()


def dpo(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return DPOIndicator(df["close"], window=period, fillna=False).dpo()


def awesome_oscillator(df: pd.DataFrame) -> pd.Series:
    return AwesomeOscillatorIndicator(df["high"], df["low"], window1=5, window2=34, fillna=False).awesome_oscillator()


def ultimate_oscillator(df: pd.DataFrame) -> pd.Series:
    return UltimateOscillator(
        df["high"], df["low"], df["close"], window1=7, window2=14, window3=28, fillna=False
    ).ultimate_oscillator()
