"""Phase A1/A2 — the backtest simulator must be lookahead-free and cost-aware.

The simulator is the pure core of the backtester: given a list of per-bar
records (OHLC + the signal that was DECIDED ON THE PREVIOUS CLOSED BAR, i.e.
actionable at this bar's open), it walks forward and produces closed trades +
an equity curve. It must never use information from a bar to act on that same
bar (no same-bar lookahead), and it must deduct fees + slippage.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from backtesting.simulator import Bar, simulate


def _bars(rows: list[dict]) -> list[Bar]:
    t0 = datetime(2024, 1, 1)
    out = []
    for i, r in enumerate(rows):
        out.append(Bar(
            ts=t0 + timedelta(hours=i),
            open=r["open"], high=r["high"], low=r["low"], close=r["close"],
            signal=r.get("signal", "NEUTRAL"), score=r.get("score", 0),
            atr=r.get("atr", 1.0),
        ))
    return out


def test_entry_fills_at_next_bar_open_not_signal_bar_close():
    # Bar 0 carries a BUY signal (decided on the prior closed bar). The fill must
    # happen at bar 0's OPEN (100), never at its close (130) — that would be lookahead.
    bars = _bars([
        {"open": 100, "high": 131, "low": 99, "close": 130, "signal": "BUY", "score": 90, "atr": 10},
        {"open": 130, "high": 200, "low": 129, "close": 199, "signal": "NEUTRAL"},  # TP hit here
    ])
    res = simulate(bars, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert len(res.trade_log) == 1
    assert res.trade_log[0].entry == 100  # next-bar open, not 130


def test_entry_bar_intrabar_high_below_tp_defers_exit():
    # Signal fires on bar1 -> entry at bar1 open (100). TP = 100 + 3*atr(10) = 130.
    # Bar1 high is only 105, so TP is NOT hit on the entry bar; exit happens on bar2
    # where the high reaches 140. (No reliance on any future bar's data to act on bar1.)
    bars = _bars([
        {"open": 50, "high": 51, "low": 49, "close": 50, "signal": "NEUTRAL"},  # warmup
        {"open": 100, "high": 105, "low": 98, "close": 104, "signal": "BUY", "score": 90, "atr": 10},
        {"open": 104, "high": 140, "low": 103, "close": 138, "signal": "NEUTRAL"},  # TP=130 hit
    ])
    res = simulate(bars, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert len(res.trade_log) == 1
    assert res.trade_log[0].entry == 100
    assert res.trade_log[0].exit_time == bars[2].ts


def test_appending_future_bars_does_not_change_closed_trades():
    # Lookahead-invariance gate: trades that close within a prefix must be identical
    # whether or not future bars are appended.
    base = _bars([
        {"open": 50, "high": 51, "low": 49, "close": 50, "signal": "BUY", "score": 90, "atr": 5},  # entry 50, tp 65, sl 42.5
        {"open": 60, "high": 64, "low": 58, "close": 63, "signal": "NEUTRAL"},  # high 64 < 65, no exit
        {"open": 63, "high": 70, "low": 62, "close": 69, "signal": "NEUTRAL"},  # high 70 >= 65 -> TP exit
    ])
    extra = _bars([{"open": 69, "high": 300, "low": 5, "close": 290, "signal": "NEUTRAL"}])
    short = simulate(base, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    long = simulate(base + extra, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert len(short.trade_log) == 1
    t_short, t_long = short.trade_log[0], long.trade_log[0]
    assert (t_short.entry, t_short.exit, t_short.exit_time) == (t_long.entry, t_long.exit, t_long.exit_time)


def test_fees_reduce_pnl():
    bars = _bars([
        {"open": 50, "high": 51, "low": 49, "close": 50, "signal": "BUY", "score": 90, "atr": 10},
        {"open": 100, "high": 140, "low": 99, "close": 138, "signal": "NEUTRAL"},  # TP=130 hit
    ])
    free = simulate(bars, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    costed = simulate(bars, fee=0.001, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert costed.trade_log[0].pnl < free.trade_log[0].pnl


def test_slippage_worsens_entry_and_exit():
    bars = _bars([
        {"open": 50, "high": 51, "low": 49, "close": 50, "signal": "BUY", "score": 90, "atr": 10},
        {"open": 100, "high": 140, "low": 99, "close": 138, "signal": "NEUTRAL"},
    ])
    free = simulate(bars, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    slipped = simulate(bars, fee=0.0, slippage=0.005, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    # BUY entry slips up (worse), exit slips down (worse) -> lower pnl
    assert slipped.trade_log[0].entry > free.trade_log[0].entry
    assert slipped.trade_log[0].pnl < free.trade_log[0].pnl


def test_no_trade_when_score_below_threshold():
    bars = _bars([
        {"open": 100, "high": 101, "low": 99, "close": 100, "signal": "BUY", "score": 40, "atr": 5},
        {"open": 100, "high": 150, "low": 99, "close": 149, "signal": "NEUTRAL"},
    ])
    res = simulate(bars, fee=0.0, slippage=0.0, min_score=65, sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert res.trade_log == []
