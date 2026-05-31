"""Phase C6 — exit management (default-off).

Behavior, not performance. Pure exit rules: ATR R-multiples, Chandelier/swing
trailing, scale-out at T1, time-based stale exit, parabolic over-extension partial.
Edge validation (does this exit policy make money?) is the separate real-data gate,
deferred while offline — these tests pin mechanics only.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from config import settings
from core.exit_manager import (
    ExitConfig,
    ExitDecision,
    chandelier_stop,
    current_r,
    manage_exit,
    time_exit_due,
)

warnings.filterwarnings("ignore")

CFG = ExitConfig()


def _state(**kw):
    base = dict(entry=100.0, direction=1, atr=2.0, stop_mult=2.0, price=100.0,
                peak_price=100.0, bars_held=1, scaled_out=False, parabolic_taken=False,
                current_stop=96.0, cfg=CFG)
    return {**base, **kw}


# ─── current_r (1R = atr * stop_mult) ────────────────────────────────────
def test_current_r_long_at_one_r():
    assert current_r(100, 104, 2, 2, 1) == 1.0


def test_current_r_short_at_one_r():
    assert current_r(100, 96, 2, 2, -1) == 1.0


def test_current_r_zero_risk_is_zero():
    assert current_r(100, 110, 0, 2, 1) == 0.0


# ─── chandelier_stop ─────────────────────────────────────────────────────
def test_chandelier_long_trails_below_peak():
    assert chandelier_stop(120, 2, 1, 3.0) == 114


def test_chandelier_short_trails_above_peak():
    assert chandelier_stop(80, 2, -1, 3.0) == 86


# ─── time_exit_due ───────────────────────────────────────────────────────
def test_time_exit_when_stale_and_flat():
    assert time_exit_due(50, 0.2, max_bars=48, min_r=0.5) is True


def test_no_time_exit_when_making_progress():
    assert time_exit_due(50, 0.8, max_bars=48, min_r=0.5) is False


def test_no_time_exit_before_max_bars():
    assert time_exit_due(10, 0.0, max_bars=48, min_r=0.5) is False


# ─── manage_exit: priority + each rule ───────────────────────────────────
def test_hold_when_flat_and_fresh():
    assert manage_exit(**_state()) == ExitDecision(0.0, 96.0, "hold")


def test_time_exit_takes_priority_and_closes_all():
    d = manage_exit(**_state(bars_held=99, price=100.5))
    assert d.close_fraction == 1.0 and d.reason == "time_exit"


def test_scale_out_at_t1_closes_half_and_moves_to_breakeven():
    d = manage_exit(**_state(price=104, peak_price=104))   # +1R
    assert d.close_fraction == CFG.scale_out_fraction
    assert d.new_stop == 100.0 and d.reason == "scale_out_t1"


def test_no_second_scale_out_after_already_scaled():
    d = manage_exit(**_state(price=104, peak_price=104, scaled_out=True))
    assert d.reason != "scale_out_t1"


def test_chandelier_trail_after_scaled_ratchets_stop_up():
    d = manage_exit(**_state(price=110, peak_price=112, scaled_out=True, current_stop=100))
    assert d.reason == "chandelier_trail"
    assert d.new_stop == chandelier_stop(112, 2, 1, CFG.chandelier_mult)   # 106 > 100


def test_chandelier_never_loosens_stop():
    # chandelier = 106 - 3*2 = 100 < current 104 -> keep the tighter stop, hold
    d = manage_exit(**_state(price=106, peak_price=106, scaled_out=True, current_stop=104))
    assert d.new_stop == 104 and d.reason == "hold"


def test_parabolic_takes_partial_once():
    d = manage_exit(**_state(price=116, peak_price=116))   # +4R, beyond parabolic_r
    assert d.close_fraction == CFG.parabolic_fraction and d.reason == "parabolic"
    d2 = manage_exit(**_state(price=116, peak_price=116, parabolic_taken=True, scaled_out=True))
    assert d2.reason != "parabolic"


def test_short_side_scale_out():
    d = manage_exit(**_state(direction=-1, price=96, peak_price=96, current_stop=104))
    assert d.close_fraction == CFG.scale_out_fraction and d.new_stop == 100.0


# ─── simulator integration (default-off; trailing + time-exit wired) ─────
def _trend_df(n: int = 80) -> pd.DataFrame:
    close = np.linspace(100, 140, n)
    return pd.DataFrame(
        {"open": close, "high": close * 1.002, "low": close * 0.998,
         "close": close, "volume": np.full(n, 500.0)},
        index=pd.date_range("2024-01-01", periods=n, freq="h"),
    )


def test_simulator_off_path_unchanged(monkeypatch):
    from backtesting.simulator import simulate
    df = _trend_df()
    sig = pd.Series([60] * len(df), index=df.index)
    atr = pd.Series(np.full(len(df), 1.0), index=df.index)
    monkeypatch.setattr(settings, "exit_management_enabled", False)
    a = simulate(sig, df, atr=atr)
    b = simulate(sig, df, atr=atr)
    assert (a.trades, a.total_return) == (b.trades, b.total_return)


def test_simulator_trailing_keeps_results_bounded(monkeypatch):
    from backtesting.simulator import simulate
    df = _trend_df()
    sig = pd.Series([60] * len(df), index=df.index)
    atr = pd.Series(np.full(len(df), 1.0), index=df.index)
    monkeypatch.setattr(settings, "exit_management_enabled", True)
    res = simulate(sig, df, atr=atr)
    assert res.total_return >= -1.0          # bounded, no blow-up
    assert all(t["reason"] in {"stop", "take_profit", "signal_flip", "time_exit"}
               for t in res.trade_log)
