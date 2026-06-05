"""Phase E3 — indicator heatmap matrix builder (pure, offline-validatable)."""
from __future__ import annotations

from types import SimpleNamespace

from core.heatmap import build_indicator_heatmap


def _sig(symbol, indicators, **layers):
    base = {l: 0 for l in ("trend", "momentum", "volatility", "volume", "pattern", "sentiment")}
    base.update({f"{k}_score": v for k, v in layers.items()})
    return SimpleNamespace(
        symbol=symbol, timeframe="1h", final_score=10, signal="BUY", regime="TRENDING_BULL",
        indicators_detail=indicators, **base,
    )


def test_symbols_preserve_input_order():
    out = build_indicator_heatmap([_sig("BTC/USDT", {}), _sig("ETH/USDT", {})])
    assert out["symbols"] == ["BTC/USDT", "ETH/USDT"]


def test_indicator_union_first_seen_order():
    out = build_indicator_heatmap([
        _sig("BTC/USDT", {"ema_stack": -70, "macd": 20}),
        _sig("ETH/USDT", {"macd": 5, "rsi_14": 30}),   # macd already seen; rsi_14 is new
    ])
    assert out["indicators"] == ["ema_stack", "macd", "rsi_14"]


def test_rows_carry_layers_and_indicator_scores():
    out = build_indicator_heatmap([_sig("BTC/USDT", {"ema_stack": -70}, trend=42, volume=-15)])
    row = out["rows"][0]
    assert row["layers"]["trend"] == 42 and row["layers"]["volume"] == -15
    assert row["layers"]["momentum"] == 0          # untouched layer defaults to 0
    assert row["indicators"] == {"ema_stack": -70}
    assert row["final_score"] == 10 and row["signal"] == "BUY" and row["regime"] == "TRENDING_BULL"


def test_missing_indicators_detail_is_empty_not_crash():
    s = _sig("BTC/USDT", None)
    out = build_indicator_heatmap([s])
    assert out["indicators"] == [] and out["rows"][0]["indicators"] == {}


def test_sparse_indicators_per_symbol():
    # ETH lacks ema_stack; the matrix only lists scores a symbol actually has
    out = build_indicator_heatmap([
        _sig("BTC/USDT", {"ema_stack": -70, "rsi_14": 20}),
        _sig("ETH/USDT", {"rsi_14": 25}),
    ])
    assert "ema_stack" in out["indicators"]
    assert "ema_stack" not in out["rows"][1]["indicators"]
    assert out["rows"][1]["indicators"]["rsi_14"] == 25


def test_empty_input():
    out = build_indicator_heatmap([])
    assert out == {"symbols": [], "indicators": [], "rows": []}


def test_nonint_meta_keys_excluded():
    # indicators_detail may carry nested meta (e.g. a persisted `_sentiment` block).
    # The heatmap must surface ONLY numeric indicator scores — never an object, which
    # would crash the frontend (it renders each value directly as a React child).
    out = build_indicator_heatmap([
        _sig("BTC/USDT", {"rsi_14": 40, "_sentiment": {"mode": "shadow", "composite": 14.0}}),
    ])
    assert out["indicators"] == ["rsi_14"]
    assert out["rows"][0]["indicators"] == {"rsi_14": 40}
