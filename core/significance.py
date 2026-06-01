"""Statistical-significance gate (Phase D1) — pure, offline-testable.

A one-sample proportion z-test used to decide whether an indicator's observed
win rate differs from a baseline (chance) enough to justify nudging its weight.
Replaces the old "nudge on every single trade" behavior, which treated one
win/loss as signal. Pure math — no DB, no network — so it is fully validated here.
"""
from __future__ import annotations

import math


def proportion_z(wins: int, n: int, baseline: float = 0.5) -> float:
    """Z-score of an observed win proportion vs `baseline` under H0 (p = baseline)."""
    if n <= 0:
        return 0.0
    se = math.sqrt(baseline * (1.0 - baseline) / n)
    if se == 0:
        return 0.0
    return (wins / n - baseline) / se


def is_significant(wins: int, n: int, *, baseline: float = 0.5,
                   min_sample: int = 30, z_threshold: float = 1.96) -> bool:
    """True only if the sample is large enough AND |z| clears the threshold."""
    return n >= min_sample and abs(proportion_z(wins, n, baseline)) >= z_threshold


def significant_direction(wins: int, n: int, *, baseline: float = 0.5,
                          min_sample: int = 30, z_threshold: float = 1.96) -> int:
    """+1 (significantly above baseline), -1 (below), or 0 (not significant / too few)."""
    if not is_significant(wins, n, baseline=baseline, min_sample=min_sample, z_threshold=z_threshold):
        return 0
    return 1 if wins / n > baseline else -1
