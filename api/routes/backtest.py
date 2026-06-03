"""Backtest runner endpoint (Phase E3).

A single backtest replays the full signal bar-by-bar (~tens of seconds), so it runs in
a background thread: POST starts a job and returns its id, GET polls for the result.
Offline + deterministic — uses the seeded synthetic fixture (A6 reference dataset).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from backtesting.engine import Backtester
from backtesting.fixtures import make_synthetic_ohlcv
from backtesting.serialize import result_to_dict


router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 20


class BacktestRequest(BaseModel):
    bars: int = Field(400, ge=280, le=800)        # > warmup(250); upper-capped to bound runtime
    min_score: int = Field(10, ge=1, le=100)
    fee: float = Field(0.001, ge=0.0, le=0.01)
    slippage: float = Field(0.0005, ge=0.0, le=0.01)


def _run(job_id: str, p: BacktestRequest) -> None:
    try:
        df = make_synthetic_ohlcv(n=p.bars)
        bt = Backtester(min_score=p.min_score, fee=p.fee, slippage=p.slippage)
        out = result_to_dict(asyncio.run(bt.run_on_df(df, None, "BACKTEST", "1h")))
        with _LOCK:
            _JOBS[job_id].update(status="done", result=out, finished_at=time.time())
    except Exception as e:
        with _LOCK:
            _JOBS[job_id].update(status="error", error=f"{type(e).__name__}: {e}", finished_at=time.time())


@router.post("")
def start(req: BacktestRequest = Body(default_factory=BacktestRequest)) -> dict:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        if len(_JOBS) >= _MAX_JOBS:   # evict the oldest finished job
            for k in sorted(_JOBS, key=lambda j: _JOBS[j].get("started_at", 0)):
                if _JOBS[k]["status"] != "running":
                    del _JOBS[k]
                    break
        _JOBS[job_id] = {"status": "running", "params": req.model_dump(), "started_at": time.time()}
    threading.Thread(target=_run, args=(job_id, req), daemon=True).start()
    return {
        "job_id": job_id,
        "status": "running",
        "note": "Synthetic reference dataset (seed=7) — a relative before/after tool, not a strategy verdict.",
    }


@router.get("/{job_id}")
def status(job_id: str) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "Unknown backtest job")
        return {"job_id": job_id, **job}
