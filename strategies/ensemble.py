"""Strategy ensemble (Phase C5).

Regime-adaptive, confidence-weighted vote across enabled strategies. Each vote is
weighted by the strategy's confidence and (optionally) its historical per-regime
win rate; the combined confidence collapses toward 0 when strategies disagree.

Win rates default to neutral (0.5) — wiring real per-strategy, per-regime win rates
from the learning engine is deferred (needs live closed trades, offline for now).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd

from core.market_regime import Regime
from strategies.base import StrategyBase, StrategySignal


class StrategyEnsemble:
    def __init__(self, strategies: Iterable[StrategyBase],
                 win_rates: Mapping[tuple[str, str], float] | None = None) -> None:
        self.strategies = list(strategies)
        self.win_rates = dict(win_rates or {})

    def _active(self, regime: Regime) -> list[StrategyBase]:
        return [s for s in self.strategies if s.enabled and (not s.regimes or regime in s.regimes)]

    def combine(self, df: pd.DataFrame, regime: Regime) -> StrategySignal:
        score_acc = conf_acc = total_w = dir_w = 0.0
        for s in self._active(regime):
            sig = s.generate_signal(df)
            if sig.confidence <= 0:
                continue
            w = (sig.confidence / 100.0) * self.win_rates.get((s.name, regime.value), 0.5)
            if w <= 0:
                continue
            score_acc += sig.score * w
            conf_acc += sig.confidence * w
            total_w += w
            dir_w += w * (1 if sig.score > 0 else -1 if sig.score < 0 else 0)
        if total_w <= 0:
            return StrategySignal(0, 0)
        score = int(round(max(-100, min(100, score_acc / total_w))))
        confidence = int(round((conf_acc / total_w) * (abs(dir_w) / total_w)))
        return StrategySignal(score, confidence)
