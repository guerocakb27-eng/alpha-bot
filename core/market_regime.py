"""Market regime detection.

Regimes: TRENDING_BULL, TRENDING_BEAR, RANGING, HIGH_VOLATILITY, SQUEEZE.
"""
from __future__ import annotations

from enum import Enum

import pandas as pd

from indicators.trend import adx, ema
from indicators.volatility import atr, bb_squeeze


class Regime(str, Enum):
    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    SQUEEZE = "SQUEEZE"


class MarketRegimeDetector:
    """Classify market state from OHLCV."""

    def detect(self, df: pd.DataFrame) -> Regime:
        if len(df) < 220:
            # Not enough history for EMA200; default to ranging
            return Regime.RANGING

        adx_vals = adx(df, period=14)
        adx_now = float(adx_vals["adx"].iloc[-1])
        plus_di = float(adx_vals["plus_di"].iloc[-1])
        minus_di = float(adx_vals["minus_di"].iloc[-1])

        ema200 = ema(df, [200])[200]
        price = float(df["close"].iloc[-1])
        ema200_now = float(ema200.iloc[-1])

        atr14 = atr(df, [14])[14]
        atr_now = float(atr14.iloc[-1])
        atr_avg = float(atr14.rolling(50).mean().iloc[-1])
        volume_ratio = float(df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1])

        # Squeeze: BB inside KC for 5+ candles
        squeeze = bb_squeeze(df)
        if squeeze.tail(5).all():
            return Regime.SQUEEZE

        # High volatility: ATR/price > 1.5x average AND volume spike
        if atr_avg > 0 and (atr_now / atr_avg) > 1.5 and volume_ratio > 1.5:
            return Regime.HIGH_VOLATILITY

        # Trending bull/bear: ADX > 25 AND price vs EMA200
        if adx_now > 25 and plus_di > minus_di and price > ema200_now:
            return Regime.TRENDING_BULL
        if adx_now > 25 and minus_di > plus_di and price < ema200_now:
            return Regime.TRENDING_BEAR

        # Ranging: ADX < 20
        if adx_now < 20:
            return Regime.RANGING

        # Transitional zone (20 ≤ ADX ≤ 25): fall back to bull/bear by price vs EMA200
        return Regime.TRENDING_BULL if price > ema200_now else Regime.TRENDING_BEAR
