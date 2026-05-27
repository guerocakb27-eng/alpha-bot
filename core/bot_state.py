"""Process-wide bot state, shared between the FastAPI routes and the bot loop.

Single source of truth for "is the bot running, in what mode, since when".
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import settings


@dataclass
class BotState:
    running: bool = False
    started_at: str | None = None
    mode: str = field(default_factory=lambda: "PAPER" if settings.paper_trading else "LIVE")
    last_cycle_at: str | None = None
    last_cycle_ms: float | None = None
    emergency_close: bool = False
    process_start: float = field(default_factory=time.time)


state = BotState()
