"""Phase B5 — tiered drawdown circuit breaker + anti-martingale sizing.

circuit_breaker_action maps signed day/week loss percentages to an action:
  NORMAL -> trade as usual
  HALVE  -> day loss in [-5, -3]  -> open at half size
  NO_NEW -> day loss <= -5        -> no new trades today
  FULL_STOP -> week loss <= -10   -> halt until manual restart (takes precedence)

Position sizing must be anti-martingale: a smaller balance (after losses) can
never produce a larger position for the same setup.
"""
from __future__ import annotations

from core.risk_manager import RiskManager, circuit_breaker_action


def test_normal_within_limits():
    assert circuit_breaker_action(-2.0, -2.0) == "NORMAL"
    assert circuit_breaker_action(0.0, 0.0) == "NORMAL"
    assert circuit_breaker_action(5.0, 5.0) == "NORMAL"  # profit


def test_halve_on_soft_daily_loss():
    assert circuit_breaker_action(-3.0, -3.0) == "HALVE"
    assert circuit_breaker_action(-4.9, -4.9) == "HALVE"


def test_no_new_on_hard_daily_loss():
    assert circuit_breaker_action(-5.0, -5.0) == "NO_NEW"
    assert circuit_breaker_action(-8.0, -8.0) == "NO_NEW"


def test_full_stop_on_weekly_drawdown():
    assert circuit_breaker_action(-1.0, -10.0) == "FULL_STOP"
    assert circuit_breaker_action(-1.0, -15.0) == "FULL_STOP"


def test_weekly_full_stop_takes_precedence_over_daily():
    assert circuit_breaker_action(-6.0, -12.0) == "FULL_STOP"


def test_position_size_anti_martingale_monotonic_in_balance():
    rm = RiskManager()
    big, _ = rm.position_size(1000, 100, 98)
    small, _ = rm.position_size(900, 100, 98)
    assert small <= big  # smaller balance after a loss must never size larger


def test_build_plan_size_multiplier_halves_quantity():
    rm = RiskManager()
    full = rm.build_plan("BUY", 100, 2.0, 1000)
    half = rm.build_plan("BUY", 100, 2.0, 1000, size_multiplier=0.5)
    assert half.quantity == full.quantity * 0.5
    assert half.size_usdt == full.size_usdt * 0.5
