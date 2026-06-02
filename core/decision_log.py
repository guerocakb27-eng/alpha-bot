"""Per-signal decision logging (Phase E1) — pure WHY-chain builder.

Turns a scored signal plus the trade/skip outcome into a structured, human-readable
explanation: the verdict, the gating reason, and the dominant layers/indicators that
drove the direction. Pure (no DB, no Loguru, no `self`) so the reasoning is unit-tested;
the bot loop persists/emits the returned record (BotEvent + Loguru) behind a flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionReason(str, Enum):
    TRADED = "traded"
    BELOW_THRESHOLD = "below_threshold"
    POSITION_EXISTS = "position_exists"
    MISSING_PRICE_DATA = "missing_price_data"


@dataclass(frozen=True)
class DecisionRecord:
    symbol: str
    timeframe: str
    final_score: int
    signal: str
    confidence: int
    regime: str
    traded: bool
    reason: DecisionReason
    top_layers: list[tuple[str, int]] = field(default_factory=list)
    top_indicators: list[tuple[str, int]] = field(default_factory=list)


def _aligned_top(scores: dict[str, int], sign: int, k: int = 3) -> list[tuple[str, int]]:
    """Items whose score agrees with `sign`, strongest-aligned first, top-k."""
    aligned = [(k_, v) for k_, v in scores.items() if v * sign > 0]
    aligned.sort(key=lambda kv: kv[1] * sign, reverse=True)
    return aligned[:k]


def explain_decision(result: Any, *, min_score: int, has_position: bool,
                     close: float | None, atr: float | None) -> DecisionRecord:
    """Decide the gating reason (threshold > existing position > price data, in the same
    order the bot loop checks them) and attach the direction's dominant drivers."""
    sign = 1 if result.final_score > 0 else -1 if result.final_score < 0 else 0
    if abs(result.final_score) < min_score:
        reason, traded = DecisionReason.BELOW_THRESHOLD, False
    elif has_position:
        reason, traded = DecisionReason.POSITION_EXISTS, False
    elif not close or not atr:
        reason, traded = DecisionReason.MISSING_PRICE_DATA, False
    else:
        reason, traded = DecisionReason.TRADED, True

    return DecisionRecord(
        symbol=result.symbol,
        timeframe=result.timeframe,
        final_score=result.final_score,
        signal=result.signal,
        confidence=result.confidence,
        regime=result.regime.value if hasattr(result.regime, "value") else str(result.regime),
        traded=traded,
        reason=reason,
        top_layers=_aligned_top(result.layers, sign),
        top_indicators=_aligned_top(result.indicators_detail, sign),
    )


def format_decision(d: DecisionRecord) -> str:
    """One-line WHY string for Loguru / the dashboard's 'why did the bot do this' panel."""
    verdict = f"TRADE {d.signal}" if d.traded else f"SKIP ({d.reason.value.replace('_', ' ')})"
    layers = ", ".join(f"{n}:{v:+d}" for n, v in d.top_layers) or "—"
    inds = ", ".join(f"{n}:{v:+d}" for n, v in d.top_indicators) or "—"
    return (f"[{d.symbol} {d.timeframe}] {verdict} | score={d.final_score:+d} "
            f"conf={d.confidence} regime={d.regime} | layers: {layers} | drivers: {inds}")


def to_metadata(d: DecisionRecord) -> dict:
    """JSON-safe record for BotEvent.event_metadata (Phase E3 'why' panel reads this back)."""
    return {
        "symbol": d.symbol, "timeframe": d.timeframe, "final_score": d.final_score,
        "signal": d.signal, "confidence": d.confidence, "regime": d.regime,
        "traded": d.traded, "reason": d.reason.value,
        "top_layers": [[n, v] for n, v in d.top_layers],
        "top_indicators": [[n, v] for n, v in d.top_indicators],
    }
