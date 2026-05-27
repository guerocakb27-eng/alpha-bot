"""Trade history endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import repository
from database.models import TradeStatus, get_db


router = APIRouter(prefix="/api/trades", tags=["trades"])


def _serialize(t) -> dict:
    return {
        "id": t.id,
        "symbol": t.symbol,
        "side": t.side.value if hasattr(t.side, "value") else t.side,
        "mode": t.mode.value if hasattr(t.mode, "value") else t.mode,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "quantity": t.quantity,
        "pnl_usdt": t.pnl_usdt,
        "pnl_pct": t.pnl_pct,
        "fees_usdt": t.fees_usdt,
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "signal_score": t.signal_score,
        "confidence": t.confidence,
        "market_regime": t.market_regime,
        "timeframe": t.timeframe,
        "stop_loss": t.stop_loss,
        "take_profit": t.take_profit,
        "status": t.status.value if hasattr(t.status, "value") else t.status,
    }


@router.get("")
def list_trades(
    symbol: str | None = None,
    status: TradeStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    rows = repository.list_trades(db, symbol, status, date_from, date_to, limit, offset)
    return {"trades": [_serialize(t) for t in rows], "limit": limit, "offset": offset}


@router.get("/{trade_id}")
def get_trade(trade_id: int, db: Session = Depends(get_db)) -> dict:
    t = repository.get_trade(db, trade_id)
    if not t:
        raise HTTPException(404, "Trade not found")
    out = _serialize(t)
    out["indicators_snapshot"] = t.indicators_snapshot
    out["notes"] = t.notes
    return out
