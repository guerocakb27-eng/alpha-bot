"""Decision history endpoint (Phase E3) — the 'why did the bot do this?' panel.

Reads back the DECISION BotEvents persisted by the bot loop when
`decision_logging_enabled` is set; returns an empty list otherwise.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import repository
from database.models import get_db


router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("")
def recent(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    return {"decisions": repository.recent_decisions(db, limit=limit)}
