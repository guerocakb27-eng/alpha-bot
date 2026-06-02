"""Indicator heatmap aggregation (Phase E3) — pure matrix builder.

Turns the latest signal per symbol into a symbol×indicator score matrix for the
dashboard heatmap. Pure (no DB, no `self`) so the shaping is unit-tested; the route
just feeds it `repository.latest_signal_per_symbol`.
"""
from __future__ import annotations

from typing import Any

LAYERS = ("trend", "momentum", "volatility", "volume", "pattern", "sentiment")


def build_indicator_heatmap(signals: list[Any]) -> dict:
    """Build {symbols, indicators, rows} from signal-like objects.

    `indicators` is the union of `indicators_detail` keys in first-seen order (stable,
    deterministic). Each row carries the 6 layer scores and that symbol's indicator
    scores; the frontend transposes (indicators as rows, symbols as columns)."""
    indicators: list[str] = []
    seen: set[str] = set()
    rows: list[dict] = []
    for s in signals:
        detail = getattr(s, "indicators_detail", None) or {}
        for k in detail:
            if k not in seen:
                seen.add(k)
                indicators.append(k)
        rows.append({
            "symbol": s.symbol,
            "timeframe": s.timeframe,
            "final_score": s.final_score,
            "signal": s.signal,
            "regime": s.regime,
            "layers": {l: getattr(s, f"{l}_score", 0) for l in LAYERS},
            "indicators": dict(detail),
        })
    return {"symbols": [r["symbol"] for r in rows], "indicators": indicators, "rows": rows}
