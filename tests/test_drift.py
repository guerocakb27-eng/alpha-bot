"""Phase D3 — concept-drift detection (offline-validatable).

Behavior + decision logic, validated here (no network). `detect_drift` is the pure
rule that decides whether LIVE performance has diverged materially below the
validated baseline it was accepted at — enough to alert and (optionally) roll back to
the last-good weights. The DB read of recent trades / weight history is the impure
shell around this pure core.
"""
from __future__ import annotations

import pytest

from config import settings
from core.drift import DriftConfig, DriftReport, detect_drift, rollback_target


CFG = DriftConfig()


# ─── detect_drift: min-sample gate ───────────────────────────────────────
def test_no_drift_below_min_sample_even_if_terrible():
    r = detect_drift(live_wr=0.0, baseline_wr=0.55, n=5, cfg=CFG)
    assert r.drifted is False and r.reason == "insufficient_sample"


# ─── detect_drift: material drop triggers ────────────────────────────────
def test_drift_when_live_drops_materially_below_baseline():
    # baseline 0.55, live 0.35 -> 0.20 absolute drop >= 0.15 default
    r = detect_drift(live_wr=0.35, baseline_wr=0.55, n=50, cfg=CFG)
    assert r.drifted is True and r.reason == "winrate_drop"
    assert r.severity == pytest.approx(0.20)


def test_no_drift_within_tolerance():
    # 0.55 -> 0.45 = 0.10 drop < 0.15 tolerance
    r = detect_drift(live_wr=0.45, baseline_wr=0.55, n=50, cfg=CFG)
    assert r.drifted is False and r.reason == "within_tolerance"


def test_no_drift_when_live_beats_baseline():
    r = detect_drift(live_wr=0.70, baseline_wr=0.55, n=50, cfg=CFG)
    assert r.drifted is False and r.severity <= 0.0


def test_exactly_at_tolerance_is_not_drift():
    # drop exactly == tolerance is not yet material (strictly greater triggers)
    r = detect_drift(live_wr=0.40, baseline_wr=0.55, n=50, cfg=DriftConfig(drop_tolerance=0.15))
    assert r.drifted is False


def test_custom_tolerance_and_min_sample():
    cfg = DriftConfig(drop_tolerance=0.05, min_sample=10)
    assert detect_drift(live_wr=0.48, baseline_wr=0.55, n=10, cfg=cfg).drifted is True
    assert detect_drift(live_wr=0.48, baseline_wr=0.55, n=9, cfg=cfg).drifted is False


# ─── rollback_target: pick the last-good weights snapshot ─────────────────
def test_rollback_picks_most_recent_positive_before_current():
    # (id, performance_score) newest-first; current is id=4 (the drifted live set)
    history = [(4, -0.2), (3, 0.1), (2, 0.9), (1, 0.4)]
    assert rollback_target(history, current_id=4) == 3   # most recent good before current


def test_rollback_skips_nonpositive_scores():
    history = [(4, -0.2), (3, 0.0), (2, -0.5), (1, 0.4)]
    assert rollback_target(history, current_id=4) == 1


def test_rollback_none_when_no_good_history():
    history = [(4, -0.2), (3, -0.1)]
    assert rollback_target(history, current_id=4) is None


def test_rollback_none_when_only_current():
    assert rollback_target([(4, 0.9)], current_id=4) is None


# ─── default-off flag is respected by callers ────────────────────────────
def test_drift_detection_flag_defaults_off():
    # Code default, independent of any deployment .env (which may enable it).
    from config import Settings
    assert Settings(_env_file=None).drift_detection_enabled is False


def test_check_drift_is_noop_when_flag_off(monkeypatch):
    # Flag off must short-circuit BEFORE any DB access (returns None, no SessionLocal use).
    monkeypatch.setattr(settings, "drift_detection_enabled", False)
    from core.learning_engine import LearningEngine
    assert LearningEngine().check_drift(baseline_wr=0.55) is None
