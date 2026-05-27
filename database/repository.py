"""Data access layer — thin wrappers around SQLAlchemy queries.

Keeps API routes free of ORM logic and makes write paths easy to test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from database.models import (
    BotEvent,
    BotSettings,
    EventSeverity,
    EventType,
    IndicatorWeights,
    OptimizationMethod,
    Signal,
    Trade,
    TradeMode,
    TradeStatus,
)


# ─── Trades ──────────────────────────────────────────────────────────
def list_trades(
    db: Session,
    symbol: str | None = None,
    status: TradeStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Trade]:
    stmt = select(Trade)
    if symbol:
        stmt = stmt.where(Trade.symbol == symbol)
    if status:
        stmt = stmt.where(Trade.status == status)
    if date_from:
        stmt = stmt.where(Trade.entry_time >= date_from)
    if date_to:
        stmt = stmt.where(Trade.entry_time <= date_to)
    stmt = stmt.order_by(desc(Trade.entry_time)).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def get_trade(db: Session, trade_id: int) -> Trade | None:
    return db.get(Trade, trade_id)


def count_open_positions(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Trade).where(Trade.status == TradeStatus.OPEN)) or 0


# ─── Signals ─────────────────────────────────────────────────────────
def insert_signal(db: Session, **fields: Any) -> Signal:
    sig = Signal(**fields)
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig


def latest_signal_per_symbol(db: Session) -> list[Signal]:
    """One row per symbol — the most recent signal."""
    sub = (
        select(Signal.symbol, func.max(Signal.timestamp).label("max_ts"))
        .group_by(Signal.symbol)
        .subquery()
    )
    stmt = select(Signal).join(
        sub, (Signal.symbol == sub.c.symbol) & (Signal.timestamp == sub.c.max_ts)
    )
    return list(db.scalars(stmt))


def signal_by_symbol(db: Session, symbol: str) -> Signal | None:
    stmt = select(Signal).where(Signal.symbol == symbol).order_by(desc(Signal.timestamp)).limit(1)
    return db.scalars(stmt).first()


# ─── Performance ─────────────────────────────────────────────────────
def performance_summary(db: Session) -> dict[str, Any]:
    closed = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.CLOSED)))
    if not closed:
        return {
            "win_rate": 0.0, "total_pnl_usdt": 0.0, "total_pnl_pct": 0.0,
            "sharpe": 0.0, "max_drawdown": 0.0, "profit_factor": 0.0,
            "trade_count": 0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    wins = [t for t in closed if t.pnl_usdt > 0]
    losses = [t for t in closed if t.pnl_usdt < 0]
    gains_sum = sum(t.pnl_usdt for t in wins)
    losses_sum = abs(sum(t.pnl_usdt for t in losses))
    return {
        "win_rate": round(len(wins) / len(closed) * 100, 2),
        "total_pnl_usdt": round(sum(t.pnl_usdt for t in closed), 2),
        "total_pnl_pct": round(sum(t.pnl_pct for t in closed), 2),
        "profit_factor": round(gains_sum / losses_sum, 2) if losses_sum > 0 else float("inf"),
        "trade_count": len(closed),
        "avg_win": round(gains_sum / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-losses_sum / len(losses), 2) if losses else 0.0,
    }


def equity_curve(db: Session, days: int = 90) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trades = list(db.scalars(
        select(Trade).where(Trade.status == TradeStatus.CLOSED, Trade.exit_time >= since).order_by(Trade.exit_time)
    ))
    equity = 1000.0
    out: list[dict[str, Any]] = []
    for t in trades:
        equity += t.pnl_usdt
        out.append({"timestamp": t.exit_time.isoformat() if t.exit_time else None, "equity": round(equity, 2)})
    return out


def performance_by_regime(db: Session) -> list[dict[str, Any]]:
    rows = list(db.execute(
        select(
            Trade.market_regime,
            func.count(Trade.id),
            func.sum(Trade.pnl_usdt),
            func.avg(Trade.pnl_pct),
        )
        .where(Trade.status == TradeStatus.CLOSED, Trade.market_regime.is_not(None))
        .group_by(Trade.market_regime)
    ))
    return [
        {"regime": r[0], "trade_count": r[1], "total_pnl": round(r[2] or 0, 2), "avg_pnl_pct": round(r[3] or 0, 2)}
        for r in rows
    ]


# ─── Weights ─────────────────────────────────────────────────────────
def current_weights(db: Session) -> dict[str, dict[str, float]]:
    """Latest weight row per regime."""
    sub = (
        select(IndicatorWeights.regime, func.max(IndicatorWeights.timestamp).label("max_ts"))
        .group_by(IndicatorWeights.regime)
        .subquery()
    )
    stmt = select(IndicatorWeights).join(
        sub, (IndicatorWeights.regime == sub.c.regime) & (IndicatorWeights.timestamp == sub.c.max_ts)
    )
    return {
        w.regime: {
            "trend": w.trend_w, "momentum": w.momentum_w, "volatility": w.volatility_w,
            "volume": w.volume_w, "pattern": w.pattern_w, "sentiment": w.sentiment_w,
        }
        for w in db.scalars(stmt)
    }


def weights_history(db: Session, regime: str | None = None, limit: int = 100) -> list[IndicatorWeights]:
    stmt = select(IndicatorWeights)
    if regime:
        stmt = stmt.where(IndicatorWeights.regime == regime)
    stmt = stmt.order_by(desc(IndicatorWeights.timestamp)).limit(limit)
    return list(db.scalars(stmt))


# ─── Settings ────────────────────────────────────────────────────────
def get_settings(db: Session) -> dict[str, Any]:
    return {s.key: s.value for s in db.scalars(select(BotSettings))}


def set_setting(db: Session, key: str, value: Any, updated_by: str | None = None) -> BotSettings:
    existing = db.get(BotSettings, key)
    if existing:
        existing.value = value
        existing.updated_by = updated_by
    else:
        existing = BotSettings(key=key, value=value, updated_by=updated_by)
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


# ─── Events ──────────────────────────────────────────────────────────
def log_event(
    db: Session,
    event_type: EventType,
    message: str,
    severity: EventSeverity = EventSeverity.INFO,
    event_metadata: dict | None = None,
) -> BotEvent:
    ev = BotEvent(event_type=event_type, message=message, severity=severity, event_metadata=event_metadata)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev
