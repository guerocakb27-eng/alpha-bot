"""Live signals endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.heatmap import build_indicator_heatmap
from database import repository
from database.models import get_db


router = APIRouter(prefix="/api/signals", tags=["signals"])


def _serialize(s) -> dict:
    return {
        "id": s.id,
        "symbol": s.symbol,
        "timestamp": s.timestamp.isoformat(),
        "timeframe": s.timeframe,
        "final_score": s.final_score,
        "signal": s.signal,
        "confidence": s.confidence,
        "regime": s.regime,
        "layers": {
            "trend": s.trend_score, "momentum": s.momentum_score, "volatility": s.volatility_score,
            "volume": s.volume_score, "pattern": s.pattern_score, "sentiment": s.sentiment_score,
        },
    }


@router.get("")
def list_signals(db: Session = Depends(get_db)) -> dict:
    rows = repository.latest_signal_per_symbol(db)
    return {"signals": [_serialize(s) for s in rows]}


# NOTE: declared before /{symbol:path} so the literal path isn't captured as a symbol.
@router.get("/heatmap")
def heatmap(db: Session = Depends(get_db)) -> dict:
    """Symbol×indicator score matrix (latest signal per symbol) for the heatmap tab."""
    return build_indicator_heatmap(repository.latest_signal_per_symbol(db))


@router.get("/{symbol:path}")
def get_signal(symbol: str, db: Session = Depends(get_db)) -> dict:
    s = repository.signal_by_symbol(db, symbol)
    if not s:
        raise HTTPException(404, f"No signals for {symbol}")
    out = _serialize(s)
    out["indicators_detail"] = s.indicators_detail
    return out
