"""Exit management (Phase C6) — pure, default-off exit policy.

Everything here is a pure function of a position's state and the current bar, so it
is unit-testable without a DB or exchange (same discipline as risk_manager). Rules,
in priority order, combined by `manage_exit`:

  time_exit  — a trade that has gone nowhere for too long is dead money -> close all
  parabolic  — a vertical over-extension (>= parabolic_r) -> bank a partial once
  scale_out  — at the first target (+scale_out_r) -> close half, stop to breakeven
  trail      — once in profit, ratchet a Chandelier stop behind the peak (never loosens)

`manage_exit` returns the full policy (incl. partial fills); the backtest simulator
currently consumes only the no-partial parts (trailing + time exit). Wiring the
partial-fill paths into the simulator (size-aware equity) and the live execution
engine (testnet) is deferred — see the upgrade plan's Phase C6 follow-ups.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExitConfig:
    stop_mult: float = 2.0            # 1R = atr * stop_mult (matches RiskConfig)
    scale_out_enabled: bool = True
    scale_out_r: float = 1.0          # first target at +1R
    scale_out_fraction: float = 0.5   # close half at T1
    breakeven_after_scale: bool = True
    chandelier_mult: float = 3.0      # trail this many ATR behind the peak (LeBeau)
    time_exit_bars: int = 48          # stale after this many bars held...
    time_exit_min_r: float = 0.5      # ...if open profit is still below this R
    parabolic_r: float = 3.0          # over-extension threshold
    parabolic_fraction: float = 0.33  # partial to bank on a parabolic spike


@dataclass(frozen=True)
class ExitDecision:
    close_fraction: float       # 0..1 of the remaining position to close now
    new_stop: float | None      # updated stop price (may equal current = unchanged)
    reason: str


def current_r(entry: float, price: float, atr: float, stop_mult: float, direction: int) -> float:
    """Open profit as an R-multiple, where 1R = atr * stop_mult."""
    risk = atr * stop_mult
    return (price - entry) * direction / risk if risk > 0 else 0.0


def chandelier_stop(peak_price: float, atr: float, direction: int, mult: float = 3.0) -> float:
    """Stop trailed `mult` ATR behind the favorable extreme since entry."""
    return peak_price - direction * atr * mult


def time_exit_due(bars_held: int, r_now: float, *, max_bars: int, min_r: float) -> bool:
    return bars_held >= max_bars and r_now < min_r


def manage_exit(
    *,
    entry: float,
    direction: int,
    atr: float,
    stop_mult: float,
    price: float,
    peak_price: float,
    bars_held: int,
    scaled_out: bool,
    parabolic_taken: bool,
    current_stop: float | None,
    cfg: ExitConfig,
) -> ExitDecision:
    r = current_r(entry, price, atr, stop_mult, direction)

    if time_exit_due(bars_held, r, max_bars=cfg.time_exit_bars, min_r=cfg.time_exit_min_r):
        return ExitDecision(1.0, current_stop, "time_exit")

    if not parabolic_taken and r >= cfg.parabolic_r:
        return ExitDecision(cfg.parabolic_fraction, current_stop, "parabolic")

    if cfg.scale_out_enabled and not scaled_out and r >= cfg.scale_out_r:
        new_stop = entry if cfg.breakeven_after_scale else current_stop
        return ExitDecision(cfg.scale_out_fraction, new_stop, "scale_out_t1")

    if r >= cfg.scale_out_r:
        ch = chandelier_stop(peak_price, atr, direction, cfg.chandelier_mult)
        if current_stop is None or (ch - current_stop) * direction > 0:   # ratchet, never loosen
            return ExitDecision(0.0, ch, "chandelier_trail")

    return ExitDecision(0.0, current_stop, "hold")
