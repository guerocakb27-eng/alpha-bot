"""Pure, lookahead-free backtest simulator (Phase A1/A2).

Separated from `engine.py` so the fill/exit/equity logic can be unit-tested
without any network or indicator computation.

Contract: each `Bar` carries the signal that is ACTIONABLE AT THAT BAR'S OPEN
(it was decided on the previous closed bar). The simulator:
  - fills entries at the bar's open (with slippage),
  - never exits a position on the same bar it was opened (no same-bar lookahead),
  - on later bars, checks SL/TP against that bar's intrabar high/low and
    opposite signals at the open,
  - deducts maker/taker fees and slippage from realized PnL.

This guarantees the value used to act on bar *t* never depends on bar *t+1*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from backtesting.metrics import max_drawdown, profit_factor, sharpe_ratio, sortino_ratio, win_rate
from config import settings
from core.exit_manager import ExitConfig, chandelier_stop, current_r, time_exit_due

_EXIT_CFG = ExitConfig()


@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    signal: str = "NEUTRAL"   # actionable at THIS bar's open
    score: int = 0
    atr: float = 0.0


@dataclass
class Trade:
    entry_time: datetime
    side: str
    entry: float
    exit_time: datetime | None = None
    exit: float | None = None
    pnl: float = 0.0          # realized return in percent, net of fees + slippage
    sl: float = 0.0
    tp: float = 0.0
    exit_reason: str = ""
    # Phase C6 exit-management bookkeeping (only consulted when the flag is on).
    peak: float = 0.0         # favorable extreme since entry (high for BUY, low for SELL)
    bars_held: int = 0
    entry_atr: float = 0.0


@dataclass
class BacktestResult:
    total_return: float
    win_rate: float
    sharpe: float
    sortino: float
    max_drawdown: float
    profit_factor: float
    trade_log: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series | None = None


def _actionable(bar: Bar, min_score: int) -> bool:
    return bar.signal in ("BUY", "SELL") and abs(bar.score) >= min_score


def _slip(price: float, side: str, slippage: float, *, is_exit: bool) -> float:
    if slippage == 0:
        return price
    # entering BUY = buy; exiting BUY = sell; entering SELL = sell; exiting SELL = buy
    buying = (side == "BUY") != is_exit
    return price * (1 + slippage) if buying else price * (1 - slippage)


def _net_pnl_pct(side: str, entry: float, exit_px: float, fee: float) -> float:
    gross = (exit_px - entry) / entry * 100 if side == "BUY" else (entry - exit_px) / entry * 100
    return gross - fee * 100 * 2  # round-trip fee (entry + exit)


def simulate(
    bars: list[Bar],
    *,
    fee: float = 0.0,
    slippage: float = 0.0,
    min_score: int = 65,
    sl_atr_mult: float = 1.5,
    tp_atr_mult: float = 3.0,
    initial_equity: float = 1.0,
) -> BacktestResult:
    open_trade: Trade | None = None
    trades: list[Trade] = []
    equity = initial_equity
    equity_vals: list[float] = []

    for bar in bars:
        # 1) Manage an existing position on THIS bar (it was opened on an earlier bar).
        if open_trade is not None:
            # Phase C6 exit management (default off): track the favorable extreme and
            # ratchet a Chandelier trailing stop once in profit, before the SL/TP check.
            open_trade.bars_held += 1
            open_trade.peak = (max(open_trade.peak, bar.high) if open_trade.side == "BUY"
                               else min(open_trade.peak, bar.low))
            _d = 1 if open_trade.side == "BUY" else -1
            _on = settings.exit_management_enabled and open_trade.entry_atr > 0
            _r = current_r(open_trade.entry, bar.close, open_trade.entry_atr, sl_atr_mult, _d) if _on else 0.0
            if _on and _r >= _EXIT_CFG.scale_out_r:
                _ch = chandelier_stop(open_trade.peak, open_trade.entry_atr, _d, _EXIT_CFG.chandelier_mult)
                if (_ch - open_trade.sl) * _d > 0:   # ratchet only in our favor
                    open_trade.sl = _ch

            exit_px: float | None = None
            reason = ""
            if open_trade.side == "BUY":
                if bar.low <= open_trade.sl:
                    exit_px, reason = open_trade.sl, "SL"
                elif bar.high >= open_trade.tp:
                    exit_px, reason = open_trade.tp, "TP"
            else:
                if bar.high >= open_trade.sl:
                    exit_px, reason = open_trade.sl, "SL"
                elif bar.low <= open_trade.tp:
                    exit_px, reason = open_trade.tp, "TP"
            if exit_px is None and _actionable(bar, min_score):
                opposite = (open_trade.side == "BUY" and bar.signal == "SELL") or (
                    open_trade.side == "SELL" and bar.signal == "BUY"
                )
                if opposite:
                    exit_px, reason = bar.open, "OPP"
            # time-based stale exit (default off): dead money after N bars with no progress
            if exit_px is None and _on and time_exit_due(
                    open_trade.bars_held, _r, max_bars=_EXIT_CFG.time_exit_bars, min_r=_EXIT_CFG.time_exit_min_r):
                exit_px, reason = bar.close, "TIME"
            if exit_px is not None:
                fill = _slip(exit_px, open_trade.side, slippage, is_exit=True)
                open_trade.exit = fill
                open_trade.exit_time = bar.ts
                open_trade.exit_reason = reason
                open_trade.pnl = _net_pnl_pct(open_trade.side, open_trade.entry, fill, fee)
                equity *= 1 + open_trade.pnl / 100
                trades.append(open_trade)
                open_trade = None

        # 2) Open a new position at THIS bar's open if flat and the signal is actionable.
        if open_trade is None and _actionable(bar, min_score):
            side = bar.signal
            entry = _slip(bar.open, side, slippage, is_exit=False)
            if side == "BUY":
                sl, tp = entry - sl_atr_mult * bar.atr, entry + tp_atr_mult * bar.atr
            else:
                sl, tp = entry + sl_atr_mult * bar.atr, entry - tp_atr_mult * bar.atr
            open_trade = Trade(entry_time=bar.ts, side=side, entry=entry, sl=sl, tp=tp,
                               peak=entry, entry_atr=bar.atr)

        equity_vals.append(equity)

    equity_series = pd.Series(equity_vals, index=[b.ts for b in bars], dtype=float)
    returns = equity_series.pct_change().fillna(0) if len(equity_series) else pd.Series(dtype=float)
    pnls = [t.pnl for t in trades]
    total_return = (equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100 if len(equity_series) else 0.0
    return BacktestResult(
        total_return=total_return,
        win_rate=win_rate(pnls) * 100,
        sharpe=sharpe_ratio(returns),
        sortino=sortino_ratio(returns),
        max_drawdown=max_drawdown(equity_series) * 100,
        profit_factor=profit_factor(pnls),
        trade_log=trades,
        equity_curve=equity_series,
    )
