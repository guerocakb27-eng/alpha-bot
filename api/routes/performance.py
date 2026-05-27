"""Performance metrics endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import repository
from database.models import get_db


router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("")
def summary(db: Session = Depends(get_db)) -> dict:
    return repository.performance_summary(db)


@router.get("/equity")
def equity(days: int = Query(90, ge=1, le=730), db: Session = Depends(get_db)) -> dict:
    return {"points": repository.equity_curve(db, days=days), "days": days}


@router.get("/by-regime")
def by_regime(db: Session = Depends(get_db)) -> dict:
    return {"breakdown": repository.performance_by_regime(db)}
