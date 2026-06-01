"""Phase C7 — volatility sizing + capped half-Kelly + correlation cap (default-off).

Behavior, not performance. Three pure, reduce-only size multipliers (each clamps to
<= 1.0, so they can only SHRINK the base risk — never inflate it, matching the
anti-martingale stance elsewhere in risk_manager). Edge validation is the separate
real-data gate (deferred offline); these tests pin the math and the wiring only.
"""
from __future__ import annotations

import pytest

from config import settings
from core.risk_manager import RiskConfig, RiskManager
from core.sizing import (
    correlation_cap,
    half_kelly_fraction,
    kelly_risk_multiplier,
    volatility_scalar,
)


# ─── volatility_scalar (inverse to ATR%, reduce-only) ────────────────────
def test_vol_scalar_at_target_is_full_size():
    assert volatility_scalar(2.0, 2.0) == 1.0


def test_vol_scalar_high_vol_halves_size():
    assert volatility_scalar(4.0, 2.0) == 0.5


def test_vol_scalar_extreme_vol_clamps_to_floor():
    assert volatility_scalar(20.0, 2.0, floor=0.25) == 0.25


def test_vol_scalar_low_vol_capped_at_one():
    assert volatility_scalar(1.0, 2.0) == 1.0   # reduce-only: never inflates


def test_vol_scalar_zero_atr_is_noop():
    assert volatility_scalar(0.0, 2.0) == 1.0


# ─── half_kelly_fraction (raw textbook math, may be negative) ────────────
def test_half_kelly_positive_edge():
    assert half_kelly_fraction(0.6, 2.0) == pytest.approx(0.2)   # (0.6 - 0.4/2)/2


def test_half_kelly_no_edge_is_zero():
    assert half_kelly_fraction(0.5, 1.0) == pytest.approx(0.0)


def test_half_kelly_negative_edge_is_negative():
    assert half_kelly_fraction(0.4, 1.0) == pytest.approx(-0.1)


# ─── kelly_risk_multiplier (sample gate + clamp policy) ──────────────────
def test_kelly_mult_below_min_trades_is_noop():
    assert kelly_risk_multiplier(0.9, 3.0, 40, 0.01, min_trades=50) == 1.0


def test_kelly_mult_strong_edge_capped_at_one():
    # half-Kelly 0.2 >> base 0.01 -> would be 20x, reduce-only cap pins it to 1.0
    assert kelly_risk_multiplier(0.6, 2.0, 100, 0.01, cap=1.0) == 1.0


def test_kelly_mult_weak_edge_scales_down():
    # W=0.505,R=1 -> f=0.01, half=0.005, /0.01 base = 0.5
    assert kelly_risk_multiplier(0.505, 1.0, 100, 0.01) == pytest.approx(0.5)


def test_kelly_mult_negative_edge_hits_floor():
    assert kelly_risk_multiplier(0.3, 1.0, 100, 0.01, floor=0.25) == 0.25


# ─── correlation_cap (penalize clustered exposure) ───────────────────────
_CORR = {("BTC/USDT", "ETH/USDT"): 0.85, ("BTC/USDT", "SOL/USDT"): 0.80,
         ("BTC/USDT", "XRP/USDT"): 0.20}


def test_corr_cap_no_open_positions_is_full_size():
    assert correlation_cap("BTC/USDT", [], _CORR) == 1.0


def test_corr_cap_uncorrelated_is_full_size():
    assert correlation_cap("BTC/USDT", ["XRP/USDT"], _CORR, threshold=0.7) == 1.0


def test_corr_cap_one_correlated_reduces():
    assert correlation_cap("BTC/USDT", ["ETH/USDT"], _CORR, threshold=0.7, penalty=0.5) == 0.5


def test_corr_cap_lookup_is_symmetric():
    # only the reversed-order key exists -> must still be found
    assert correlation_cap("ETH/USDT", ["BTC/USDT"], _CORR, threshold=0.7, penalty=0.5) == 0.5


def test_corr_cap_many_correlated_clamps_to_floor():
    assert correlation_cap("BTC/USDT", ["ETH/USDT", "SOL/USDT"], _CORR,
                           threshold=0.7, penalty=0.5, floor=0.25) == 0.25


# ─── RiskManager wiring (default-off, reduce-only) ───────────────────────
def test_build_plan_unchanged_when_all_c7_flags_off():
    rm = RiskManager()
    base = rm.build_plan("BUY", 100.0, 2.0, 1000.0)
    same = rm.build_plan("BUY", 100.0, 2.0, 1000.0, atr_pct=8.0,
                         kelly=(0.3, 1.0, 100), new_symbol="BTC/USDT",
                         open_symbols=["ETH/USDT"], corr_lookup=_CORR)
    assert same.quantity == base.quantity   # flags off -> inputs ignored


def test_build_plan_vol_sizing_shrinks_quantity(monkeypatch):
    rm = RiskManager()
    base = rm.build_plan("BUY", 100.0, 2.0, 1000.0).quantity
    monkeypatch.setattr(settings, "vol_sizing_enabled", True)
    hot = rm.build_plan("BUY", 100.0, 2.0, 1000.0, atr_pct=8.0).quantity
    assert hot < base and hot > 0


def test_build_plan_correlation_cap_shrinks_quantity(monkeypatch):
    rm = RiskManager(RiskConfig(corr_threshold=0.7))
    base = rm.build_plan("BUY", 100.0, 2.0, 1000.0).quantity
    monkeypatch.setattr(settings, "correlation_cap_enabled", True)
    capped = rm.build_plan("BUY", 100.0, 2.0, 1000.0, new_symbol="BTC/USDT",
                           open_symbols=["ETH/USDT"], corr_lookup=_CORR).quantity
    assert capped < base
