"""Phase E3 — risk posture snapshot for the dashboard gauge (offline-validatable).

`risk_posture` is the pure read-only view over the same tier logic as the live
circuit breaker; `repository.realized_drawdown` is its closed-trade data source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.risk_manager import risk_posture
from database import repository
from database.models import Trade, TradeSide, TradeStatus


# ─── pure posture mapping ────────────────────────────────────────────
def test_posture_normal():
    p = risk_posture(-2.0, -2.0)
    assert p["action"] == "NORMAL" and p["halted"] is False and p["size_multiplier"] == 1.0


def test_posture_halve_on_soft_daily():
    p = risk_posture(-3.0, -3.0)
    assert p["action"] == "HALVE" and p["halted"] is False and p["size_multiplier"] == 0.5


def test_posture_no_new_on_hard_daily():
    p = risk_posture(-5.0, -5.0)
    assert p["action"] == "NO_NEW" and p["halted"] is True and p["size_multiplier"] == 0.0


def test_posture_full_stop_weekly_takes_precedence():
    p = risk_posture(-6.0, -12.0)
    assert p["action"] == "FULL_STOP" and p["halted"] is True


def test_posture_exposes_negative_thresholds_and_rounds():
    p = risk_posture(-3.456, -1.234)
    assert p["thresholds"] == {"day_soft": -3.0, "day_hard": -5.0, "week_hard": -10.0}
    assert p["day_loss_pct"] == -3.46 and p["week_loss_pct"] == -1.23


def test_posture_custom_thresholds():
    # tighter soft tier: -2% day now trips HALVE
    assert risk_posture(-2.0, 0.0, day_soft=2.0)["action"] == "HALVE"


# ─── realized_drawdown data source (deterministic clock to avoid midnight flake) ──
_NOW = datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc)
_DAY_START = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def _closed(db, pnl_pct, exit_time):
    db.add(Trade(symbol="BTC/USDT", side=TradeSide.BUY, entry_price=100.0, quantity=1.0,
                 pnl_pct=pnl_pct, status=TradeStatus.CLOSED, exit_time=exit_time))
    db.commit()


def test_realized_drawdown_sums_today_and_week(test_db):
    with test_db() as db:
        _closed(db, -2.0, _DAY_START + timedelta(hours=2))   # today + this week
        _closed(db, -1.5, _DAY_START + timedelta(hours=5))   # today + this week
        _closed(db, -3.0, _NOW - timedelta(days=3))          # this week only
        dd = repository.realized_drawdown(db, now=_NOW)
    assert round(dd["day_loss_pct"], 2) == -3.5
    assert round(dd["week_loss_pct"], 2) == -6.5


def test_realized_drawdown_excludes_open_and_old_trades(test_db):
    with test_db() as db:
        _closed(db, -4.0, _NOW - timedelta(days=10))   # outside the week
        db.add(Trade(symbol="ETH/USDT", side=TradeSide.BUY, entry_price=1.0,
                     quantity=1.0, pnl_pct=-9.0, status=TradeStatus.OPEN))  # open: excluded
        db.commit()
        dd = repository.realized_drawdown(db, now=_NOW)
    assert dd["day_loss_pct"] == 0.0 and dd["week_loss_pct"] == 0.0
