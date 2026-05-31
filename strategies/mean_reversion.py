"""Mean-reversion strategies (Phase C5)."""
from __future__ import annotations

import pandas as pd

from core.market_regime import Regime
from indicators.momentum import rsi
from indicators.trend import sma
from strategies.base import StrategyBase, StrategySignal


class ConnorsRsi2Strategy(StrategyBase):
    """Connors RSI(2) mean reversion (Connors & Alvarez, *Short Term Trading
    Strategies That Work*): inside the 200-SMA trend, fade 2-period RSI extremes —
    buy deep-oversold dips in an uptrend, sell overbought pops in a downtrend.
    """

    name = "connors_rsi2"
    regimes = frozenset({Regime.RANGING})
    enabled = False

    def generate_signal(self, df: pd.DataFrame) -> StrategySignal:
        if len(df) < 200:
            return StrategySignal(0, 0)
        ma = sma(df, [200])[200].iloc[-1]
        r = rsi(df, [2])[2].iloc[-1]
        if pd.isna(ma) or pd.isna(r):
            return StrategySignal(0, 0)
        uptrend = float(df["close"].iloc[-1]) > float(ma)
        r = float(r)
        if uptrend and r < 10:
            return StrategySignal(70, 75)    # oversold dip to buy in an uptrend
        if (not uptrend) and r > 90:
            return StrategySignal(-70, 75)   # overbought pop to sell in a downtrend
        if uptrend and r > 90:
            return StrategySignal(-30, 50)   # stretched within an uptrend — mild fade
        if (not uptrend) and r < 10:
            return StrategySignal(30, 50)
        return StrategySignal(0, 0)
