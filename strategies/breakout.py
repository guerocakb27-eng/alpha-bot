"""Breakout strategies (Phase C5)."""
from __future__ import annotations

import pandas as pd

from core.market_regime import Regime
from indicators.volatility import donchian_channel
from strategies.base import StrategyBase, StrategySignal


class DonchianBreakoutStrategy(StrategyBase):
    """Donchian-channel breakout — the Turtle system (Dennis & Eckhardt): go with a
    close beyond the prior N-bar extreme. Uses the *previous* window's high/low
    (shifted by one) so the breakout bar can't leak into its own channel.
    """

    name = "donchian_breakout"
    regimes = frozenset({Regime.TRENDING_BULL, Regime.TRENDING_BEAR, Regime.HIGH_VOLATILITY})
    enabled = False

    def generate_signal(self, df: pd.DataFrame) -> StrategySignal:
        if len(df) < 21:
            return StrategySignal(0, 0)
        dc = donchian_channel(df, period=20)
        upper, lower = dc["upper"].shift(1).iloc[-1], dc["lower"].shift(1).iloc[-1]
        if pd.isna(upper) or pd.isna(lower):
            return StrategySignal(0, 0)
        close = float(df["close"].iloc[-1])
        if close > float(upper):
            return StrategySignal(70, 70)
        if close < float(lower):
            return StrategySignal(-70, 70)
        return StrategySignal(0, 0)
