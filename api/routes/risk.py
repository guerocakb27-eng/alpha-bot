"""Risk posture endpoint (Phase E3) — the dashboard drawdown/risk gauge.

Combines realized day/week PnL% (closed trades) with the live circuit-breaker
thresholds into a read-only snapshot. Same tier logic as the pre-trade breaker.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.risk_manager import RiskConfig, risk_posture
from database import repository
from database.models import get_db


router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("")
def risk(db: Session = Depends(get_db)) -> dict:
    cfg = RiskConfig.from_settings(db)
    dd = repository.realized_drawdown(db)
    return risk_posture(
        dd["day_loss_pct"], dd["week_loss_pct"],
        day_soft=cfg.day_soft_loss_pct, day_hard=cfg.day_hard_loss_pct, week_hard=cfg.week_hard_loss_pct,
    )
