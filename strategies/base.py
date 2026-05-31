"""Strategy ensemble base types (Phase C5)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from core.market_regime import Regime


@dataclass(frozen=True)
class StrategySignal:
    score: int        # -100..+100 directional
    confidence: int   # 0..100


class StrategyBase(ABC):
    """A single trading strategy: OHLCV -> directional score + confidence.

    Subclasses set `name`, the `regimes` they apply to (empty = all), and ship with
    `enabled = False` until they show positive OOS edge (kept in code, not deleted).
    """

    name: str = "base"
    regimes: frozenset[Regime] = frozenset()
    enabled: bool = False

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> StrategySignal:
        ...
