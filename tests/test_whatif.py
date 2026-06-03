"""Phase E3 — what-if re-scoring (pure, offline-validatable).

whatif_score re-runs the DEFAULT regime-weighted aggregation under candidate weights and
must stay in lockstep with aggregate_layers (the shared live path).
"""
from __future__ import annotations

from core.signal_engine import aggregate_layers, whatif_score

# Fixed local weights (sum to 1.0) — deliberately NOT the live WEIGHTS_BY_REGIME dict,
# which other tests (learning/optuna) mutate in place; keeps this test order-independent.
W = {"trend": 0.35, "momentum": 0.25, "volume": 0.15, "volatility": 0.10, "pattern": 0.05, "sentiment": 0.10}


def test_parity_with_aggregate_layers():
    ls = {"trend": 80, "momentum": 60, "volume": 40, "volatility": 0, "pattern": 0, "sentiment": 0}
    assert whatif_score(ls, W, mode="weighted")["final_score"] == aggregate_layers(ls, W, "weighted")
    assert whatif_score(ls, W, mode="confluence")["final_score"] == aggregate_layers(ls, W, "confluence")


def test_label_thresholds():
    assert whatif_score({k: 100 for k in W}, W, min_score=65)["signal"] == "BUY"
    assert whatif_score({k: -100 for k in W}, W, min_score=65)["signal"] == "SELL"
    assert whatif_score({k: 0 for k in W}, W, min_score=65)["signal"] == "NEUTRAL"


def test_min_score_boundary_is_inclusive():
    # all layers = ms, weights sum to 1.0 -> final = ms exactly -> BUY (>=)
    ms = 50
    out = whatif_score({k: ms for k in W}, W, min_score=ms)
    assert out["final_score"] == ms and out["signal"] == "BUY"


def test_confluence_dampens_conflicting_layers():
    mixed = {"trend": 80, "momentum": 80, "volume": 80, "volatility": -80, "pattern": -80, "sentiment": -80}
    weighted = whatif_score(mixed, W, mode="weighted")["final_score"]
    confl = whatif_score(mixed, W, mode="confluence")["final_score"]
    assert abs(confl) <= abs(weighted)


def test_missing_layers_default_to_zero():
    out = whatif_score({"trend": 100}, W)            # only trend; 100 * 0.35 = 35
    assert out["final_score"] == 35 and out["signal"] == "NEUTRAL"


def test_candidate_weights_change_score():
    ls = {"trend": 100, "momentum": 0, "volume": 0, "volatility": 0, "pattern": 0, "sentiment": 0}
    trend_heavy = {**{k: 0.0 for k in W}, "trend": 1.0}
    assert whatif_score(ls, trend_heavy)["final_score"] == 100
