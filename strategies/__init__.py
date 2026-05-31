"""Curated strategy ensemble (Phase C5)."""
from __future__ import annotations

from strategies.base import StrategyBase, StrategySignal
from strategies.breakout import DonchianBreakoutStrategy
from strategies.ensemble import StrategyEnsemble
from strategies.mean_reversion import ConnorsRsi2Strategy
from strategies.trend import MaCrossStrategy

# Curated set — one canonical strategy per family. Each ships disabled until it
# shows positive OOS edge (kept in code); expand only after the set proves out.
CURATED: list[StrategyBase] = [
    MaCrossStrategy(),
    ConnorsRsi2Strategy(),
    DonchianBreakoutStrategy(),
]


def default_ensemble(win_rates=None) -> StrategyEnsemble:
    return StrategyEnsemble(CURATED, win_rates=win_rates)


__all__ = [
    "CURATED", "StrategyBase", "StrategySignal", "StrategyEnsemble", "default_ensemble",
    "MaCrossStrategy", "ConnorsRsi2Strategy", "DonchianBreakoutStrategy",
]
