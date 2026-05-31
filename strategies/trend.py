"""Trend strategies (Phase C5)."""
from __future__ import annotations

import pandas as pd

from core.market_regime import Regime
from indicators.trend import ema
from strategies.base import StrategyBase, StrategySignal


class MaCrossStrategy(StrategyBase):
    """50/200 EMA crossover — the classic golden/death-cross trend filter (Murphy,
    *Technical Analysis of the Financial Markets*). Long while the fast average leads
    the slow one; a fresh cross is the high-confidence trigger.
    """

    name = "ma_cross_50_200"
    regimes = frozenset({Regime.TRENDING_BULL, Regime.TRENDING_BEAR})
    enabled = False

    def generate_signal(self, df: pd.DataFrame) -> StrategySignal:
        if len(df) < 200:
            return StrategySignal(0, 0)
        emas = ema(df, [50, 200])
        f, s = emas[50].dropna(), emas[200].dropna()
        if len(f) < 2 or len(s) < 2:
            return StrategySignal(0, 0)
        fn, sn, fp, sp = float(f.iloc[-1]), float(s.iloc[-1]), float(f.iloc[-2]), float(s.iloc[-2])
        if fp <= sp and fn > sn:
            return StrategySignal(80, 80)    # golden cross
        if fp >= sp and fn < sn:
            return StrategySignal(-80, 80)   # death cross
        if fn > sn:
            return StrategySignal(40, 50)
        if fn < sn:
            return StrategySignal(-40, 50)
        return StrategySignal(0, 0)
