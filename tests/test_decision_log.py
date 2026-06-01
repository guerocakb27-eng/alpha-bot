"""Phase E1 — per-signal decision logging (offline-validatable).

Behavior, validated here (no network). `explain_decision` turns a scored signal plus
the trade/skip outcome into a structured, human-readable WHY chain: the verdict, the
gating reason, and the top contributing layers/indicators. Pure — no DB, no Loguru —
so the reasoning is unit-tested; the caller just persists/emits the returned record.
"""
from __future__ import annotations

from types import SimpleNamespace

from config import settings
from core.decision_log import DecisionReason, explain_decision, format_decision


def _result(score=72, signal="BUY", regime="TRENDING_BULL",
            layers=None, indicators=None):
    return SimpleNamespace(
        symbol="BTC/USDT", timeframe="1h", final_score=score, signal=signal, confidence=64,
        regime=SimpleNamespace(value=regime),
        layers=layers or {"trend": 60, "momentum": 40, "volatility": -10, "volume": 30,
                          "pattern": 0, "sentiment": 0},
        indicators_detail=indicators or {"ema_stack": 70, "macd": 65, "rsi_14": 55,
                                         "supertrend": 50, "cci": -20},
    )


# ─── verdict + gating reason ─────────────────────────────────────────────
def test_traded_when_above_threshold_and_no_position():
    d = explain_decision(_result(score=72), min_score=65, has_position=False,
                         close=100.0, atr=2.0)
    assert d.traded is True and d.reason == DecisionReason.TRADED


def test_skip_below_threshold():
    d = explain_decision(_result(score=40), min_score=65, has_position=False,
                         close=100.0, atr=2.0)
    assert d.traded is False and d.reason == DecisionReason.BELOW_THRESHOLD


def test_skip_when_position_already_open():
    d = explain_decision(_result(score=80), min_score=65, has_position=True,
                         close=100.0, atr=2.0)
    assert d.traded is False and d.reason == DecisionReason.POSITION_EXISTS


def test_skip_when_price_data_missing():
    d = explain_decision(_result(score=80), min_score=65, has_position=False,
                         close=None, atr=None)
    assert d.traded is False and d.reason == DecisionReason.MISSING_PRICE_DATA


def test_threshold_check_precedes_position_check():
    # below threshold AND has position -> the threshold reason wins (it's checked first)
    d = explain_decision(_result(score=10), min_score=65, has_position=True,
                         close=100.0, atr=2.0)
    assert d.reason == DecisionReason.BELOW_THRESHOLD


# ─── reasoning chain: top contributors aligned with the signal direction ─
def test_top_contributors_are_direction_aligned_and_ranked():
    d = explain_decision(_result(score=72, signal="BUY"), min_score=65,
                         has_position=False, close=100.0, atr=2.0)
    # only positive (BUY-aligned) indicators, strongest first, cci(-20) excluded
    assert d.top_indicators == [("ema_stack", 70), ("macd", 65), ("rsi_14", 55)]


def test_top_contributors_for_sell_are_negative():
    ind = {"supertrend": -60, "macd": -50, "rsi_14": 20, "ema_stack": -30}
    d = explain_decision(_result(score=-70, signal="SELL", indicators=ind),
                         min_score=65, has_position=False, close=100.0, atr=2.0)
    assert d.top_indicators == [("supertrend", -60), ("macd", -50), ("ema_stack", -30)]


def test_dominant_layers_ranked_by_aligned_magnitude():
    d = explain_decision(_result(score=72, signal="BUY"), min_score=65,
                         has_position=False, close=100.0, atr=2.0)
    # trend(60) > momentum(40) > volume(30); volatility(-10) opposes BUY, excluded
    assert d.top_layers == [("trend", 60), ("momentum", 40), ("volume", 30)]


def test_record_carries_identity_and_score():
    d = explain_decision(_result(score=72, regime="RANGING"), min_score=65,
                         has_position=False, close=100.0, atr=2.0)
    assert (d.symbol, d.timeframe, d.final_score, d.regime) == ("BTC/USDT", "1h", 72, "RANGING")


# ─── format_decision: human-readable WHY string ──────────────────────────
def test_format_includes_verdict_reason_and_drivers():
    d = explain_decision(_result(score=72, signal="BUY"), min_score=65,
                         has_position=False, close=100.0, atr=2.0)
    text = format_decision(d)
    assert "BTC/USDT" in text and "BUY" in text
    assert "ema_stack" in text and "trend" in text


def test_format_skip_states_the_reason():
    d = explain_decision(_result(score=40), min_score=65, has_position=False,
                         close=100.0, atr=2.0)
    text = format_decision(d)
    assert "SKIP" in text and "below" in text.lower()


# ─── default-off flag for verbose decision logging ───────────────────────
def test_decision_logging_flag_defaults_off():
    assert settings.decision_logging_enabled is False
