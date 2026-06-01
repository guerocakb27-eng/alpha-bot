"""Concept-drift detection (Phase D3) — pure, offline-testable.

When LIVE performance diverges materially below the baseline the active weights were
ACCEPTED at (Phase D2's OOS gate), the edge has likely decayed — alert and optionally
roll back to the last-good weight snapshot. The detector and the rollback-target
picker are pure; the DB read of recent trades / IndicatorWeights history is the impure
shell the caller wraps around them.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DriftConfig:
    min_sample: int = 30           # don't judge drift on too few live trades
    drop_tolerance: float = 0.15   # win-rate may slip this far below baseline before it's "drift"


@dataclass(frozen=True)
class DriftReport:
    drifted: bool
    severity: float   # baseline_wr - live_wr (positive = live is worse); <=0 means live >= baseline
    reason: str


def detect_drift(live_wr: float, baseline_wr: float, n: int, *, cfg: DriftConfig) -> DriftReport:
    """Flag drift when the recent live win rate has fallen MORE than `drop_tolerance`
    below the validated baseline, over at least `min_sample` trades."""
    severity = baseline_wr - live_wr
    if n < cfg.min_sample:
        return DriftReport(False, severity, "insufficient_sample")
    if severity > cfg.drop_tolerance + 1e-9:   # epsilon: a drop exactly AT tolerance isn't drift
        return DriftReport(True, severity, "winrate_drop")
    return DriftReport(False, severity, "within_tolerance")


def rollback_target(history: Sequence[tuple[int, float]], current_id: int) -> int | None:
    """Pick the id of the most recent weight snapshot BEFORE `current_id` with a
    positive performance score. `history` is (id, performance_score) newest-first.
    Returns None when there is no good prior snapshot to fall back to."""
    seen_current = False
    for wid, score in history:
        if wid == current_id:
            seen_current = True
            continue
        if seen_current and score > 0:
            return wid
    return None
