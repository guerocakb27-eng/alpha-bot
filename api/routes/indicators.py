"""Live indicator values endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request


router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.get("/{symbol:path}")
async def indicators_for_symbol(symbol: str, request: Request, timeframe: str = Query("1h")) -> dict:
    """Compute current indicator values + scores live (no DB).

    Uses the shared SignalEngine instance attached to app.state.
    """
    engine = getattr(request.app.state, "signal_engine", None)
    if engine is None:
        raise HTTPException(503, "Signal engine not initialized")
    result = await engine.analyze(symbol, timeframe)
    return {
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "timestamp": result.timestamp.isoformat(),
        "regime": result.regime.value,
        "final_score": result.final_score,
        "signal": result.signal,
        "confidence": result.confidence,
        "layers": result.layers,
        "indicators": result.indicators_detail,
        "extras": {
            "close": result.extras.get("close"),
            "atr_14": result.extras.get("atr_14"),
            "candle_patterns": result.extras.get("candle_patterns", {}),
            "chart_patterns": result.extras.get("chart_patterns", {}),
        },
    }
