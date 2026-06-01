"""Position-size modifiers (Phase C7) — pure, reduce-only.

Three independent multipliers that the RiskManager can fold into base position size.
Every one is clamped to <= 1.0, so they can only SHRINK risk, never inflate it —
the same anti-martingale stance as the rest of risk_manager. All pure functions of
explicit inputs (no DB, no `self`), so they unit-test without any fixtures.

The Kelly inputs (win rate, payoff, sample count) and the correlation matrix are
supplied by the caller; sourcing them live from the learning engine / a price-matrix
calculator is deferred (needs closed trades + network, offline for now).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def volatility_scalar(atr_pct: float, target_atr_pct: float, *, floor: float = 0.25) -> float:
    """Scale inversely with volatility: full size at/below target ATR%, shrinking toward
    `floor` as ATR% rises above it. Reduce-only (never > 1.0). Zero ATR -> no-op."""
    if atr_pct <= 0 or target_atr_pct <= 0:
        return 1.0
    return max(floor, min(1.0, target_atr_pct / atr_pct))


def half_kelly_fraction(win_rate: float, payoff: float) -> float:
    """Half of the textbook Kelly fraction f* = W - (1-W)/R. May be negative (no edge)."""
    if payoff <= 0:
        return 0.0
    return (win_rate - (1.0 - win_rate) / payoff) / 2.0


def kelly_risk_multiplier(
    win_rate: float,
    payoff: float,
    n_trades: int,
    base_risk_frac: float,
    *,
    min_trades: int = 50,
    cap: float = 1.0,
    floor: float = 0.1,
) -> float:
    """Half-Kelly expressed as a multiple of the bot's base risk fraction, gated on a
    minimum sample. Reduce-only: a strong edge is capped at `cap` (we never bet MORE
    than base risk on a noisy estimate); a weak/negative edge scales down to `floor`."""
    if n_trades < min_trades or base_risk_frac <= 0:
        return 1.0
    return max(floor, min(cap, half_kelly_fraction(win_rate, payoff) / base_risk_frac))


def _corr(a: str, b: str, lookup: Mapping[tuple[str, str], float]) -> float:
    if (a, b) in lookup:
        return lookup[(a, b)]
    return lookup.get((b, a), 0.0)


def correlation_cap(
    new_symbol: str,
    open_symbols: Sequence[str],
    corr_lookup: Mapping[tuple[str, str], float],
    *,
    threshold: float = 0.7,
    penalty: float = 0.5,
    floor: float = 0.25,
) -> float:
    """Shrink size by `penalty` for each already-open position correlated with the new
    symbol above `threshold` (compounding), clamped at `floor`. No clustered exposure
    -> 1.0. Lookup is order-insensitive."""
    n = sum(1 for s in open_symbols if abs(_corr(new_symbol, s, corr_lookup)) >= threshold)
    return max(floor, penalty ** n)
