"""Phase E3 — backtest result serialization + request validation (fast, no backtest run)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from api.routes.backtest import BacktestRequest
from backtesting.serialize import result_to_dict


def _eq(n):
    return pd.Series([1.0 + i * 0.01 for i in range(n)], index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _trade(pnl=1.0, closed=True):
    return SimpleNamespace(
        entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc), side="BUY", entry=100.12345,
        exit_time=datetime(2024, 1, 2, tzinfo=timezone.utc) if closed else None,
        exit=101.5 if closed else None, pnl=pnl, exit_reason="TP" if closed else "",
    )


def _result(pf=2.5, n_eq=400, trades=None):
    return SimpleNamespace(
        total_return=12.345, win_rate=66.66, sharpe=1.234, sortino=2.0, max_drawdown=9.99,
        profit_factor=pf, trade_log=trades or [], equity_curve=_eq(n_eq),
    )


# ─── serializer ──────────────────────────────────────────────────────
def test_equity_downsampled_under_cap():
    out = result_to_dict(_result(n_eq=1000), max_points=150)
    assert 0 < len(out["equity"]) <= 150
    assert set(out["equity"][0]) == {"ts", "equity"}


def test_infinite_profit_factor_becomes_none():
    assert result_to_dict(_result(pf=float("inf")))["metrics"]["profit_factor"] is None


def test_metrics_rounded_and_trade_count():
    out = result_to_dict(_result(trades=[_trade(), _trade(-2.0)]))
    assert out["metrics"]["total_return"] == 12.35 and out["metrics"]["win_rate"] == 66.7
    assert out["metrics"]["trades"] == 2


def test_trades_truncated_and_shaped():
    out = result_to_dict(_result(trades=[_trade() for _ in range(80)]), max_trades=50)
    assert len(out["trades"]) == 50
    t = out["trades"][0]
    assert t["side"] == "BUY" and t["exit_reason"] == "TP" and t["pnl"] == 1.0 and isinstance(t["entry"], float)


def test_open_trade_has_null_exit():
    out = result_to_dict(_result(trades=[_trade(closed=False)]))
    assert out["trades"][0]["exit"] is None and out["trades"][0]["exit_time"] is None


def test_none_equity_curve_yields_empty():
    r = _result()
    r.equity_curve = None
    assert result_to_dict(r)["equity"] == []


# ─── request validation / clamping ───────────────────────────────────
def test_request_defaults():
    r = BacktestRequest()
    assert r.bars == 400 and r.min_score == 10 and r.fee == 0.001 and r.slippage == 0.0005


def test_request_rejects_out_of_range():
    with pytest.raises(ValidationError):
        BacktestRequest(bars=100)            # below warmup floor
    with pytest.raises(ValidationError):
        BacktestRequest(bars=5000)           # above runtime cap
    with pytest.raises(ValidationError):
        BacktestRequest(slippage=0.5)        # 50% slippage is nonsense
