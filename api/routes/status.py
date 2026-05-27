"""Bot status, start/stop, mode toggle."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from core.bot_state import state as bot_state
from database import repository
from database.models import EventSeverity, EventType, get_db


router = APIRouter(prefix="/api", tags=["status"])


class ModeChange(BaseModel):
    mode: str
    confirm_live: bool = False


@router.get("/status")
def bot_status(db: Session = Depends(get_db)) -> dict:
    return {
        "running": bot_state.running,
        "mode": bot_state.mode,
        "started_at": bot_state.started_at,
        "open_positions": repository.count_open_positions(db),
        "testnet": settings.binance_testnet,
        "uptime_seconds": int(time.time() - bot_state.process_start),
        "last_cycle_at": bot_state.last_cycle_at,
        "last_cycle_ms": bot_state.last_cycle_ms,
    }


@router.post("/bot/start")
def start_bot(db: Session = Depends(get_db)) -> dict:
    bot_state.running = True
    bot_state.started_at = datetime.now(timezone.utc).isoformat()
    repository.log_event(db, EventType.BOT_START, "Bot started", EventSeverity.INFO)
    return {"running": True}


@router.post("/bot/stop")
def stop_bot(db: Session = Depends(get_db)) -> dict:
    bot_state.running = False
    repository.log_event(db, EventType.BOT_STOP, "Bot stopped (positions remain open)", EventSeverity.INFO)
    return {"running": False}


@router.post("/bot/emergency-stop")
def emergency_stop(db: Session = Depends(get_db)) -> dict:
    bot_state.emergency_close = True
    bot_state.running = False
    repository.log_event(
        db, EventType.BOT_STOP, "EMERGENCY STOP — all positions queued for market close",
        EventSeverity.CRITICAL, event_metadata={"emergency": True},
    )
    return {"running": False, "close_all_queued": True}


@router.post("/bot/mode")
def change_mode(payload: ModeChange = Body(...), db: Session = Depends(get_db)) -> dict:
    if payload.mode not in {"PAPER", "LIVE"}:
        raise HTTPException(400, "mode must be PAPER or LIVE")
    if payload.mode == "LIVE" and not payload.confirm_live:
        raise HTTPException(400, "Switching to LIVE requires confirm_live=true")
    old = bot_state.mode
    bot_state.mode = payload.mode
    repository.log_event(
        db, EventType.MODE_CHANGE, f"Mode changed: {old} → {payload.mode}",
        EventSeverity.WARNING if payload.mode == "LIVE" else EventSeverity.INFO,
        event_metadata={"old": old, "new": payload.mode},
    )
    return {"mode": bot_state.mode}
