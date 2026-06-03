"""Phase E4 — anomaly detection (pure detectors) + win-rate-collapse wiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.anomaly import AnomalyConfig, repeated_rejections, slippage_spike, winrate_collapse
from core.learning_engine import LearningEngine
from database.models import EventType, Trade, TradeSide, TradeStatus

CFG = AnomalyConfig()


# ─── winrate_collapse ────────────────────────────────────────────────
def test_winrate_collapse_fires_on_big_drop():
    a = winrate_collapse(live_wr=0.30, baseline_wr=0.60, n=40, cfg=CFG)
    assert a and a.kind == "winrate_collapse" and round(a.severity, 2) == 0.30


def test_winrate_collapse_silent_within_tolerance():
    assert winrate_collapse(0.55, 0.60, 40, cfg=CFG) is None      # 5% drop < 20%


def test_winrate_collapse_needs_min_sample():
    assert winrate_collapse(0.0, 1.0, 5, cfg=CFG) is None         # only 5 trades


# ─── repeated_rejections ─────────────────────────────────────────────
def test_repeated_rejections_fires():
    a = repeated_rejections([True] * 18 + [False] * 2, cfg=CFG)   # 18/20 = 90%
    assert a and a.kind == "repeated_rejections"


def test_repeated_rejections_silent_below_ratio():
    assert repeated_rejections([True] * 10 + [False] * 10, cfg=CFG) is None  # 50%


def test_repeated_rejections_needs_full_window():
    assert repeated_rejections([True] * 10, cfg=CFG) is None      # < rej_window


# ─── slippage_spike ──────────────────────────────────────────────────
def test_slippage_spike_vs_baseline():
    a = slippage_spike(observed_bps=30.0, baseline_bps=8.0, cfg=CFG)  # 3.75x
    assert a and a.kind == "slippage_spike"


def test_slippage_below_floor_ignored():
    assert slippage_spike(observed_bps=2.0, baseline_bps=0.1, cfg=CFG) is None


def test_slippage_no_baseline_absolute_outlier():
    assert slippage_spike(observed_bps=20.0, baseline_bps=0.0, cfg=CFG) is not None   # >= 5*3
    assert slippage_spike(observed_bps=8.0, baseline_bps=0.0, cfg=CFG) is None        # above floor, not outlier


# ─── check_anomalies wiring (DB shell) ───────────────────────────────
def _trade(db, win, hours_ago):
    db.add(Trade(symbol="BTC/USDT", side=TradeSide.BUY, entry_price=100.0, quantity=1.0,
                 pnl_usdt=(5.0 if win else -5.0), status=TradeStatus.CLOSED,
                 exit_time=datetime.now(timezone.utc) - timedelta(hours=hours_ago)))


def test_check_anomalies_noop_when_disabled(test_db, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "anomaly_alerts_enabled", False)
    with test_db() as db:
        for i in range(30):
            _trade(db, win=False, hours_ago=i)
        db.commit()
    assert LearningEngine().check_anomalies() == []


def test_check_anomalies_persists_winrate_collapse(test_db, monkeypatch):
    from config import settings
    from database import repository
    monkeypatch.setattr(settings, "anomaly_alerts_enabled", True)
    with test_db() as db:
        # newest 20 are losses, older 80 are wins -> recent WR 0%, baseline 80%
        for i in range(20):
            _trade(db, win=False, hours_ago=i)          # most recent
        for i in range(80):
            _trade(db, win=True, hours_ago=100 + i)
        db.commit()

        out = LearningEngine().check_anomalies(recent_window=20, baseline_window=100)
        assert len(out) == 1 and out[0]["kind"] == "winrate_collapse"

        events = repository.recent_anomalies(db)
        assert len(events) == 1
        assert events[0]["kind"] == "winrate_collapse" and events[0]["severity"] == "WARNING"
