"""Anomaly detection (Phase E4) — pure, offline-testable.

Three independent detectors flag operational trouble worth a dashboard alert:
  - winrate_collapse   — recent win rate has fallen well below the longer-run baseline
  - repeated_rejections — most recent signals keep getting rejected (stuck/misconfigured)
  - slippage_spike     — a fill's slippage is far above the recent baseline

Each is a pure function returning an Anomaly or None; the caller (LearningEngine) wraps
the DB reads and persists/alerts on what comes back.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AnomalyConfig:
    wr_min_sample: int = 20        # don't judge win-rate collapse on too few recent trades
    wr_drop: float = 0.20          # recent WR this far below baseline -> collapse
    rej_window: int = 20           # how many recent decisions to inspect
    rej_ratio: float = 0.80        # >= this fraction rejected -> anomaly
    slip_mult: float = 3.0         # observed slippage >= mult x baseline -> spike
    slip_min_bps: float = 5.0      # ignore slippage below this floor (noise)


@dataclass(frozen=True)
class Anomaly:
    kind: str          # winrate_collapse | repeated_rejections | slippage_spike
    severity: float    # comparable magnitude (drop fraction, reject ratio, slippage x)
    message: str


def winrate_collapse(live_wr: float, baseline_wr: float, n: int, *, cfg: AnomalyConfig) -> Anomaly | None:
    """Recent win rate has dropped MORE than `wr_drop` below the longer-run baseline."""
    if n < cfg.wr_min_sample:
        return None
    drop = baseline_wr - live_wr
    if drop > cfg.wr_drop + 1e-9:
        return Anomaly("winrate_collapse", drop,
                       f"win rate {live_wr:.0%} is {drop:.0%} below baseline {baseline_wr:.0%} over last {n} trades")
    return None


def repeated_rejections(rejected_flags: Sequence[bool], *, cfg: AnomalyConfig) -> Anomaly | None:
    """At least `rej_ratio` of the most recent `rej_window` decisions were rejected."""
    if len(rejected_flags) < cfg.rej_window:
        return None
    window = list(rejected_flags)[:cfg.rej_window]
    rej = sum(1 for x in window if x)
    ratio = rej / cfg.rej_window
    if ratio >= cfg.rej_ratio:
        return Anomaly("repeated_rejections", ratio, f"{rej}/{cfg.rej_window} recent signals rejected ({ratio:.0%})")
    return None


def slippage_spike(observed_bps: float, baseline_bps: float, *, cfg: AnomalyConfig) -> Anomaly | None:
    """A fill's slippage (bps) is far above the recent baseline (or an absolute outlier
    when there's no baseline yet). Sub-floor slippage is ignored as noise."""
    if observed_bps < cfg.slip_min_bps:
        return None
    if baseline_bps <= 0:
        if observed_bps >= cfg.slip_min_bps * cfg.slip_mult:
            return Anomaly("slippage_spike", observed_bps / cfg.slip_min_bps,
                           f"slippage {observed_bps:.1f}bps with no baseline")
        return None
    ratio = observed_bps / baseline_bps
    if ratio >= cfg.slip_mult:
        return Anomaly("slippage_spike", ratio,
                       f"slippage {observed_bps:.1f}bps is {ratio:.1f}x baseline {baseline_bps:.1f}bps")
    return None
