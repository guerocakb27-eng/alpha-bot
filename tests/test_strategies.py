"""Phase C5 — curated strategy ensemble (default-off, ships disabled).

Behavior, not performance. Each strategy is a pure score+confidence over OHLCV;
the ensemble does regime-adaptive, confidence-weighted (optionally win-rate-tilted)
voting. OOS edge validation is the separate real-data gate (deferred while offline),
so every curated strategy ships with enabled=False.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from config import settings
from core.market_regime import MarketRegimeDetector, Regime
from core.signal_engine import score_signal
from strategies import CURATED
from strategies.base import StrategyBase, StrategySignal
from strategies.breakout import DonchianBreakoutStrategy
from strategies.ensemble import StrategyEnsemble
from strategies.mean_reversion import ConnorsRsi2Strategy
from strategies.trend import MaCrossStrategy

warnings.filterwarnings("ignore")


def _ohlcv(close, vol: float = 500.0) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    o = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": o, "high": np.maximum(o, close) * 1.001, "low": np.minimum(o, close) * 0.999,
         "close": close, "volume": np.full(len(close), vol)},
        index=pd.date_range("2024-01-01", periods=len(close), freq="h"),
    )


# ─── individual strategies (sign + bounds; pure, lookahead-free) ─────────
def test_ma_cross_uptrend_is_bullish():
    sig = MaCrossStrategy().generate_signal(_ohlcv(np.linspace(100, 200, 260)))
    assert sig.score > 0 and 0 <= sig.confidence <= 100


def test_ma_cross_downtrend_is_bearish():
    assert MaCrossStrategy().generate_signal(_ohlcv(np.linspace(200, 100, 260))).score < 0


def test_ma_cross_short_series_is_flat():
    assert MaCrossStrategy().generate_signal(_ohlcv(np.linspace(100, 110, 50))) == StrategySignal(0, 0)


def test_connors_rsi2_buys_oversold_dip_in_uptrend():
    close = np.concatenate([np.linspace(100, 200, 255), [198.0, 193.0]])
    assert ConnorsRsi2Strategy().generate_signal(_ohlcv(close)).score > 0


def test_connors_rsi2_sells_overbought_pop_in_downtrend():
    close = np.concatenate([np.linspace(200, 100, 255), [102.0, 107.0]])
    assert ConnorsRsi2Strategy().generate_signal(_ohlcv(close)).score < 0


def test_connors_rsi2_short_series_is_flat():
    assert ConnorsRsi2Strategy().generate_signal(_ohlcv(np.linspace(100, 110, 50))) == StrategySignal(0, 0)


def test_donchian_breakout_up_is_bullish():
    assert DonchianBreakoutStrategy().generate_signal(_ohlcv(np.r_[np.full(25, 100.0), 120.0])).score > 0


def test_donchian_breakout_down_is_bearish():
    assert DonchianBreakoutStrategy().generate_signal(_ohlcv(np.r_[np.full(25, 100.0), 80.0])).score < 0


def test_donchian_no_breakout_is_flat():
    assert DonchianBreakoutStrategy().generate_signal(_ohlcv(np.full(30, 100.0))) == StrategySignal(0, 0)


def test_curated_strategies_ship_disabled():
    assert CURATED and all(s.enabled is False for s in CURATED)


# ─── ensemble combination math (precise, via stubs) ─────────────────────
class _Stub(StrategyBase):
    def __init__(self, name, sig, *, enabled=True, regimes=frozenset()):
        self.name, self._sig, self.enabled, self.regimes = name, sig, enabled, regimes

    def generate_signal(self, df) -> StrategySignal:
        return self._sig


_R = Regime.RANGING


def test_ensemble_no_active_strategy_is_flat():
    e = StrategyEnsemble([_Stub("a", StrategySignal(80, 90), enabled=False)])
    assert e.combine(None, _R) == StrategySignal(0, 0)


def test_ensemble_skips_regime_mismatch():
    e = StrategyEnsemble([_Stub("a", StrategySignal(80, 90), regimes=frozenset({Regime.TRENDING_BULL}))])
    assert e.combine(None, _R) == StrategySignal(0, 0)


def test_ensemble_agreeing_strategies_reinforce():
    e = StrategyEnsemble([_Stub("a", StrategySignal(60, 80)), _Stub("b", StrategySignal(80, 80))])
    s = e.combine(None, _R)
    assert s.score == 70 and s.confidence == 80


def test_ensemble_opposing_strategies_cancel():
    e = StrategyEnsemble([_Stub("a", StrategySignal(80, 80)), _Stub("b", StrategySignal(-80, 80))])
    assert e.combine(None, _R) == StrategySignal(0, 0)


def test_ensemble_winrate_tilts_vote():
    e = StrategyEnsemble(
        [_Stub("good", StrategySignal(80, 80)), _Stub("bad", StrategySignal(-80, 80))],
        win_rates={("good", _R.value): 0.9, ("bad", _R.value): 0.1},
    )
    assert e.combine(None, _R).score > 0


# ─── integration: default-off + flag-on wiring ──────────────────────────
def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 8 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def test_ensemble_off_by_default():
    df = _df().iloc[:290]
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert "ensemble" not in res.indicators_detail


def test_ensemble_on_with_enabled_strategy_records_score(monkeypatch):
    df = _df().iloc[:290]
    monkeypatch.setattr(settings, "strategy_ensemble_enabled", True)
    for s in CURATED:
        monkeypatch.setattr(s, "enabled", True)
    res = score_signal(df, MarketRegimeDetector().detect(df), symbol="X", timeframe="1h")
    assert "ensemble" in res.indicators_detail
    assert -100 <= res.final_score <= 100
