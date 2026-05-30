"""Phase B4 — risk tunables are runtime-configurable via RiskConfig / BotSettings.

Defaults must match the legacy constants (no behavior change out of the box), and
a BotSettings override must actually flow through to RiskManager's decisions.
"""
from __future__ import annotations

from types import SimpleNamespace

from core import risk_manager as rm
from core.risk_manager import RiskConfig, RiskManager, circuit_breaker_action


class FakeDB:
    """Minimal stand-in: db.scalars(select(BotSettings)) -> the given rows."""
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, *_a, **_k):
        return iter(self._rows)


def test_defaults_match_legacy_constants():
    c = RiskConfig()
    assert c.risk_per_trade_pct == rm.RISK_PER_TRADE_PCT
    assert c.max_open_positions == rm.MAX_OPEN_POSITIONS
    assert c.sl_atr_mult == rm.SL_ATR_MULT
    assert c.rr_ratio == rm.RR_RATIO
    assert c.week_hard_loss_pct == rm.WEEK_HARD_LOSS_PCT


def test_from_settings_overrides_matching_keys_and_coerces_types():
    rows = [
        SimpleNamespace(key="risk_per_trade_pct", value=2.0),
        SimpleNamespace(key="max_open_positions", value=5),
        SimpleNamespace(key="sl_atr_mult", value=2.5),
        SimpleNamespace(key="unrelated_setting", value={"x": 1}),  # ignored
    ]
    cfg = RiskConfig.from_settings(FakeDB(rows))
    assert cfg.risk_per_trade_pct == 2.0
    assert cfg.max_open_positions == 5 and isinstance(cfg.max_open_positions, int)
    assert cfg.sl_atr_mult == 2.5
    assert cfg.max_position_pct == rm.MAX_POSITION_PCT  # untouched default


def test_bad_value_is_ignored_and_keeps_default():
    cfg = RiskConfig.from_settings(FakeDB([SimpleNamespace(key="rr_ratio", value="not_a_number")]))
    assert cfg.rr_ratio == rm.RR_RATIO


def test_riskmanager_uses_config_for_stop_loss():
    default = RiskManager().stop_loss("BUY", 100.0, 1.0)            # 1.5*ATR -> 98.5
    custom = RiskManager(RiskConfig(sl_atr_mult=2.0)).stop_loss("BUY", 100.0, 1.0)  # 2.0*ATR -> 98.0
    assert default == 98.5
    assert custom == 98.0


def test_riskmanager_uses_config_for_position_size():
    # Wide stop so the risk-based size (not the notional cap) binds.
    one_pct, _ = RiskManager().position_size(1000, 100, 50)               # risk 1% -> qty 0.2
    two_pct, _ = RiskManager(RiskConfig(risk_per_trade_pct=2.0)).position_size(1000, 100, 50)  # -> 0.4
    assert round(one_pct, 6) == 0.2
    assert round(two_pct, 6) == 0.4


def test_circuit_breaker_action_honors_custom_thresholds():
    assert circuit_breaker_action(-2.0, -2.0) == "NORMAL"                 # default soft = -3
    assert circuit_breaker_action(-2.0, -2.0, day_soft=1.5) == "HALVE"    # custom soft = -1.5
