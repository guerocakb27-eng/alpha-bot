"""TradingView webhook receiver. Validates HMAC + rate-limits per IP."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.auth import require_rate_limit, verify_signature
from database import repository
from database.models import EventSeverity, EventType, get_db


router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@router.post("/tradingview")
async def receive_tradingview(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    db: Session = Depends(get_db),
    _rl: None = Depends(require_rate_limit),
) -> dict:
    body = await request.body()

    if not verify_signature(body, x_signature):
        repository.log_event(
            db, EventType.ERROR, "Rejected TradingView webhook (bad signature)",
            EventSeverity.WARNING,
            event_metadata={"ip": request.client.host if request.client else None},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Body must be JSON")

    required = {"symbol", "signal", "score", "timeframe"}
    if not required.issubset(payload):
        raise HTTPException(400, f"Missing fields: {required - set(payload)}")

    repository.log_event(
        db, EventType.TRADE_OPEN, f"Webhook received: {payload['signal']} {payload['symbol']} score={payload['score']}",
        EventSeverity.INFO, event_metadata=payload,
    )
    # Actual order placement runs through ExecutionEngine (Phase 4).
    return {"accepted": True, "queued": True}
