"""What-if scoring endpoint (Phase E3) — re-score layer scores under candidate weights.

Pure: delegates to core.signal_engine.whatif_score (no DB, no network), so the dashboard
slider experiment tracks the same default scoring path the live engine uses.
"""
from __future__ import annotations

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from config import MIN_SIGNAL_SCORE
from core.signal_engine import whatif_score


router = APIRouter(prefix="/api/whatif", tags=["whatif"])


class WhatIfRequest(BaseModel):
    layer_scores: dict[str, float] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    mode: str = "weighted"
    min_score: int = MIN_SIGNAL_SCORE


@router.post("")
def whatif(req: WhatIfRequest = Body(...)) -> dict:
    return whatif_score(req.layer_scores, req.weights, mode=req.mode, min_score=req.min_score)
