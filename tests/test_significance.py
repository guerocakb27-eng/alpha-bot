"""Phase D1 — statistical-significance gate for weight updates (default-off).

Behavior + statistics, both validatable OFFLINE (no network needed, unlike Phase C
edge validation). The pure stats are pinned to hand-computable values; the engine
test proves the gate suppresses single-trade noise and only nudges on a significant,
established win/loss direction.
"""
from __future__ import annotations

import pytest

from config import settings
from core.significance import is_significant, proportion_z, significant_direction


# ─── proportion_z (one-sample proportion z-test vs p0) ───────────────────
def test_z_at_baseline_is_zero():
    assert proportion_z(50, 100, 0.5) == pytest.approx(0.0)


def test_z_above_baseline_is_positive():
    # (0.60 - 0.50) / sqrt(0.25/100) = 0.10 / 0.05 = 2.0
    assert proportion_z(60, 100, 0.5) == pytest.approx(2.0)


def test_z_below_baseline_is_negative():
    assert proportion_z(40, 100, 0.5) == pytest.approx(-2.0)


def test_z_zero_sample_is_zero():
    assert proportion_z(0, 0, 0.5) == 0.0


# ─── is_significant (min-sample gate AND |z| threshold) ──────────────────
def test_significant_strong_large_sample():
    assert is_significant(60, 100, baseline=0.5, min_sample=30, z_threshold=1.96) is True


def test_not_significant_weak_signal():
    # 55/100 -> z = 1.0 < 1.96
    assert is_significant(55, 100, baseline=0.5, min_sample=30, z_threshold=1.96) is False


def test_min_sample_gate_blocks_small_n_even_if_extreme():
    # 9/10 -> z ~ 2.53 (would pass z) but n=10 < min_sample 30
    assert is_significant(9, 10, baseline=0.5, min_sample=30, z_threshold=1.96) is False


# ─── significant_direction (0 / +1 / -1) ─────────────────────────────────
def test_direction_up_on_significant_high_winrate():
    assert significant_direction(60, 100, baseline=0.5, min_sample=30, z_threshold=1.96) == 1


def test_direction_down_on_significant_low_winrate():
    assert significant_direction(40, 100, baseline=0.5, min_sample=30, z_threshold=1.96) == -1


def test_direction_zero_when_not_significant():
    assert significant_direction(55, 100, baseline=0.5, min_sample=30, z_threshold=1.96) == 0


def test_direction_zero_below_min_sample():
    assert significant_direction(9, 10, baseline=0.5, min_sample=30, z_threshold=1.96) == 0


# ─── engine wiring: gate suppresses single-trade noise (default-off) ─────
from types import SimpleNamespace

from core.learning_engine import LearningEngine


def _win_trade(tid=1, won=True):
    # rsi_14 is always the top BUY contributor -> deterministic target indicator.
    return SimpleNamespace(
        id=tid, side=SimpleNamespace(value="BUY"), pnl_usdt=(10.0 if won else -10.0),
        indicators_snapshot={"rsi_14": 80, "macd": 70, "ema_stack": 60},
    )


def _rsi_weight(eng: LearningEngine) -> float:
    return eng._indicator_layer_weights["momentum"]["rsi_14"]


def test_gate_off_nudges_on_a_single_trade(monkeypatch):
    monkeypatch.setattr(settings, "significance_gate_enabled", False)
    eng = LearningEngine()
    base = _rsi_weight(eng)
    eng._attribution_update(None, _win_trade())
    assert _rsi_weight(eng) > base   # legacy per-trade behavior preserved


def test_gate_on_does_not_nudge_before_min_sample(monkeypatch):
    monkeypatch.setattr(settings, "significance_gate_enabled", True)
    eng = LearningEngine()
    base = _rsi_weight(eng)
    for i in range(10):                       # 10 wins < min_sample
        eng._attribution_update(None, _win_trade(i))
    assert _rsi_weight(eng) == pytest.approx(base)   # held: not enough evidence


def test_gate_on_nudges_after_significant_sample(monkeypatch):
    monkeypatch.setattr(settings, "significance_gate_enabled", True)
    eng = LearningEngine()
    base = _rsi_weight(eng)
    for i in range(40):                       # 40 wins -> highly significant
        eng._attribution_update(None, _win_trade(i))
    assert _rsi_weight(eng) > base            # nudged up once evidence accrued
