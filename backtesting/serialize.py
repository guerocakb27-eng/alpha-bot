"""JSON-safe view of a BacktestResult for the dashboard backtest runner (Phase E3).

Pure: downsamples the equity curve, truncates the trade log, and coerces non-finite
metrics (inf profit factor, NaN ratios) to null so the payload is valid JSON.
"""
from __future__ import annotations

import math
from typing import Any


def _finite(v: float | None) -> float | None:
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def result_to_dict(result: Any, *, max_points: int = 150, max_trades: int = 50) -> dict:
    eq = result.equity_curve
    points: list[dict] = []
    if eq is not None and len(eq):
        step = max(1, math.ceil(len(eq) / max_points))   # ceil so the result never exceeds max_points
        points = [{"ts": ts.isoformat(), "equity": float(v)} for ts, v in list(eq.items())[::step]]

    trades = [
        {
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "side": t.side,
            "entry": round(t.entry, 4),
            "exit": round(t.exit, 4) if t.exit is not None else None,
            "pnl": round(t.pnl, 3),
            "exit_reason": t.exit_reason,
        }
        for t in result.trade_log[:max_trades]
    ]

    return {
        "metrics": {
            "total_return": _finite(round(result.total_return, 2)),
            "win_rate": _finite(round(result.win_rate, 1)),
            "sharpe": _finite(round(result.sharpe, 2)),
            "sortino": _finite(round(result.sortino, 2)),
            "max_drawdown": _finite(round(result.max_drawdown, 2)),
            "profit_factor": _finite(round(result.profit_factor, 2)),
            "trades": len(result.trade_log),
        },
        "equity": points,
        "trades": trades,
    }
