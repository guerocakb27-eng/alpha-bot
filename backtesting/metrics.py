"""Performance metrics: Sharpe, Sortino, Max Drawdown, Profit Factor."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 365 * 24) -> float:
    """Annualized Sharpe assuming returns are per-bar log/simple returns. Default = hourly crypto."""
    r = returns.dropna()
    if r.std() == 0 or len(r) < 2:
        return 0.0
    return float((r.mean() / r.std()) * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int = 365 * 24) -> float:
    r = returns.dropna()
    downside = r[r < 0]
    if downside.std() == 0 or len(r) < 2:
        return 0.0
    return float((r.mean() / downside.std()) * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    """Returns max drawdown as a fraction (e.g., 0.25 = 25% DD)."""
    eq = equity.dropna()
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    dd = (eq - peak) / peak
    return float(abs(dd.min()))


def profit_factor(trade_pnls: list[float]) -> float:
    gains = sum(p for p in trade_pnls if p > 0)
    losses = abs(sum(p for p in trade_pnls if p < 0))
    return float(gains / losses) if losses > 0 else float("inf") if gains > 0 else 0.0


def win_rate(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    wins = sum(1 for p in trade_pnls if p > 0)
    return wins / len(trade_pnls)


def calmar_ratio(returns: pd.Series, equity: pd.Series, periods_per_year: int = 365 * 24) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    annual_return = returns.mean() * periods_per_year
    return float(annual_return / mdd)
