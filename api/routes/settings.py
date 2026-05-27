"""Settings + indicator-weights endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import repository
from database.models import EventSeverity, EventType, get_db


router = APIRouter(prefix="/api", tags=["settings"])


class SettingsUpdate(BaseModel):
    updates: dict[str, Any]
    updated_by: str | None = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return repository.get_settings(db)


@router.post("/settings")
def update_settings(payload: SettingsUpdate = Body(...), db: Session = Depends(get_db)) -> dict:
    changed: list[str] = []
    for k, v in payload.updates.items():
        repository.set_setting(db, k, v, payload.updated_by)
        changed.append(k)
    repository.log_event(
        db, EventType.SETTINGS_CHANGE, f"Settings updated: {changed}", EventSeverity.INFO,
        event_metadata={"updates": payload.updates, "by": payload.updated_by},
    )
    return {"changed": changed, "settings": repository.get_settings(db)}


@router.get("/weights")
def current_weights(db: Session = Depends(get_db)) -> dict:
    return repository.current_weights(db)


@router.get("/weights/history")
def weights_history(regime: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    rows = repository.weights_history(db, regime=regime, limit=limit)
    return {
        "history": [
            {
                "id": w.id,
                "timestamp": w.timestamp.isoformat(),
                "regime": w.regime,
                "weights": {
                    "trend": w.trend_w, "momentum": w.momentum_w, "volatility": w.volatility_w,
                    "volume": w.volume_w, "pattern": w.pattern_w, "sentiment": w.sentiment_w,
                },
                "performance_score": w.performance_score,
                "sample_size": w.sample_size,
                "optimization_method": w.optimization_method.value if hasattr(w.optimization_method, "value") else w.optimization_method,
            }
            for w in rows
        ]
    }
