"""Phase C4 — volume gate + signal freshness + market structure (default-off).

Behavior, not performance. Three pure, lookahead-free filters that modulate the
final score only when their flag is on. Edge validation is the separate real-data
gate (deferred while offline).
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from config import INDICATOR_WEIGHTS_WITHIN_LAYER, settings
from core import _scoring
from core.market_regime import MarketRegimeDetector
from core.quality_filters import market_structure, signal_freshness, volume_confirmation
from core.signal_engine import score_signal

warnings.filterwarnings("ignore")


# ─── volume_confirmation ────────────────────────────────────────────────
def test_volume_above_average_is_full_strength():
    assert volume_confirmation([100.0] * 20 + [300.0]) == 1.0


def test_volume_far_below_average_clamps_to_floor():
    assert volume_confirmation([100.0] * 20 + [30.0], floor=0.5) == 0.5


def test_volume_moderately_below_average_scales_down():
    assert volume_confirmation([100.0] * 20 + [70.0], floor=0.5) == pytest.approx(0.7)


def test_volume_insufficient_history_is_noop():
    assert volume_confirmation([100.0] * 10) == 1.0


# ─── signal_freshness ───────────────────────────────────────────────────
def test_fresh_cross_on_last_bar_is_full_strength():
    assert signal_freshness([1, 1, 1, 1, 5], [3, 3, 3, 3, 3]) == 1.0


def test_stale_cross_decays_to_floor():
    fast = [1] + [5] * 11
    assert signal_freshness(fast, [3] * 12, max_age=10, floor=0.3) == pytest.approx(0.3)


def test_recent_cross_partially_decayed():
    # cross at i=2, two bars old -> 1 - 0.7 * 2/10
    assert signal_freshness([1, 1, 5, 5, 5], [3] * 5, max_age=10, floor=0.3) == pytest.approx(0.86)


def test_no_cross_is_treated_as_stale():
    assert signal_freshness([5] * 8, [3] * 8, floor=0.3) == 0.3


# ─── market_structure ───────────────────────────────────────────────────
_UP_HIGH = [10, 11, 12, 20, 12, 11, 10, 11, 12, 30, 12, 11, 10]   # swing highs 20 -> 30 (HH)
_UP_LOW = [9, 8, 7, 3, 7, 8, 9, 8, 7, 6, 7, 8, 9]                 # swing lows 3 -> 6 (HL)
_DN_HIGH = [10, 11, 12, 30, 12, 11, 10, 11, 12, 20, 12, 11, 10]   # 30 -> 20 (LH)
_DN_LOW = [9, 8, 7, 6, 7, 8, 9, 8, 7, 3, 7, 8, 9]                 # 6 -> 3 (LL)


def test_higher_high_and_higher_low_is_bullish():
    assert market_structure(_UP_HIGH, _UP_LOW) == 60


def test_lower_high_and_lower_low_is_bearish():
    assert market_structure(_DN_HIGH, _DN_LOW) == -60


def test_broadening_structure_is_neutral():
    assert market_structure(_UP_HIGH, _DN_LOW) == 0   # HH but LL -> no clean trend


def test_too_short_for_swings_is_neutral():
    assert market_structure([1, 2, 3], [1, 2, 3]) == 0


# ─── integration: default-off + flag-on wiring ──────────────────────────
def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 8 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_all_c4_filters_off_by_default():
    df = _df().iloc[:290]
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert "structure" not in res.indicators_detail
    assert "volume_confirmation" not in res.extras
    assert "freshness" not in res.extras


def test_structure_filter_on_records_score(monkeypatch):
    df = _df().iloc[:290]
    monkeypatch.setattr(settings, "structure_filter_enabled", True)
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert "structure" in res.indicators_detail
    assert -100 <= res.final_score <= 100


def test_volume_gate_on_dampens_low_volume(monkeypatch):
    df = _df().iloc[:290].copy()
    df.iloc[-1, df.columns.get_loc("volume")] = 1.0   # force a low-volume final bar
    regime = MarketRegimeDetector().detect(df)
    off = score_signal(df, regime, symbol="X", timeframe="1h").final_score
    monkeypatch.setattr(settings, "volume_gate_enabled", True)
    on = score_signal(df, regime, symbol="X", timeframe="1h")
    assert on.extras["volume_confirmation"] < 1.0
    assert abs(on.final_score) <= abs(off)


def test_freshness_on_records_multiplier(monkeypatch):
    df = _df().iloc[:290]
    monkeypatch.setattr(settings, "freshness_enabled", True)
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert 0.0 < res.extras["freshness"] <= 1.0
    assert -100 <= res.final_score <= 100


# ─── C4 dead-indicator reclaim (behavior-preserving by construction) ─────
# score_bb_width/bb_squeeze/atr_regime always returned 0, so their term in the
# volatility layer sum was 0*weight = 0. Removing them + their weights leaves the
# sum identical (and confidence() already filters zeros), so no score changes —
# only three always-zero observability keys disappear.
_DEAD = {"bb_width", "bb_squeeze", "atr_regime"}


def test_volatility_layer_has_only_live_indicators():
    assert set(INDICATOR_WEIGHTS_WITHIN_LAYER["volatility"]) == {"bb_percent_b", "keltner", "donchian"}


def test_dead_scoring_functions_are_gone():
    assert not any(hasattr(_scoring, f"score_{name}") for name in _DEAD)


def test_result_omits_dead_indicator_keys():
    df = _df().iloc[:290]
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert _DEAD.isdisjoint(res.indicators_detail)
