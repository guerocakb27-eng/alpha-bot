"""score_signal sentiment modes: shadow never moves the score; live moves it only when gated in."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import WEIGHTS_BY_REGIME, settings
from core.market_regime import MarketRegimeDetector
from core.sentiment_engine import SentimentScore
from core.signal_engine import aggregate_layers, score_signal


def _df(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = 100 * np.exp((rng.normal(0.0006, 0.012, n) + np.sin(np.linspace(0, 6 * np.pi, n)) * 0.012).cumsum())
    o = c * (1 + rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.012, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.012, n))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": rng.uniform(100, 1000, n)},
                        index=pd.date_range("2024-01-01", periods=n, freq="h"))


def _sent(composite: float, *, active_sources: int, coverage: float, age: int = 5) -> SentimentScore:
    return SentimentScore(
        symbol="X", composite_score=composite, component_scores={}, fetch_latency_seconds=age,
        timestamp=datetime.now(timezone.utc), active_sources=active_sources, coverage=coverage,
        data_age_seconds=age,
    )


def _regime(df):
    return MarketRegimeDetector().detect(df)


def test_shadow_is_byte_identical_to_no_sentiment():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    shadow = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="shadow")
    assert shadow.final_score == base.final_score          # excluded from the score
    assert shadow.layers["sentiment"] == 80                # but kept for display


def test_live_gate_pass_moves_the_score():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    live = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="live")
    assert live.final_score != base.final_score
    # final equals aggregation over the displayed layers (sentiment included)
    assert live.final_score == aggregate_layers(live.layers, WEIGHTS_BY_REGIME[regime.value], settings.aggregation_mode)


def test_live_gate_fail_neutralizes():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=1, coverage=0.25)   # below min_sources / min_coverage
    base = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=None)
    live = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="live")
    assert live.final_score == base.final_score          # gated out
    assert live.layers["sentiment"] == 80                # still displayed


def test_extras_report_mode_and_gate():
    df = _df().iloc[:290]
    regime = _regime(df)
    sent = _sent(80, active_sources=3, coverage=0.60)
    res = score_signal(df, regime, symbol="X", timeframe="1h", sentiment=sent, sentiment_mode="shadow")
    s = res.extras["sentiment"]
    assert s["mode"] == "shadow" and s["in_score"] is False and s["active_sources"] == 3
