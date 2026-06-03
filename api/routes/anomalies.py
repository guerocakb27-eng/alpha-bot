"""Anomaly alerts endpoint (Phase E4) — feeds the dashboard alerts banner.

Reads back the ANOMALY events the learning engine persists when
`anomaly_alerts_enabled` is set; empty otherwise.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import repository
from database.models import get_db


router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("")
def recent(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> dict:
    return {"anomalies": repository.recent_anomalies(db, limit=limit)}
