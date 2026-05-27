"""WebSocket connection manager and broadcast helpers."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class ConnectionManager:
    """Tracks open WebSocket clients and broadcasts JSON events to all of them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS client connected ({} total)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS client disconnected ({} total)", len(self._connections))

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        """Send {type, data, ts} to every connected client. Dead clients are dropped."""
        msg = json.dumps({
            "type": event_type,
            "data": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }, default=str)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(msg)
            except Exception as e:
                logger.warning("Dropping dead WS client: {}", e)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def ws_endpoint(ws: WebSocket) -> None:
    """Public WebSocket entry point with heartbeat + reconnect support."""
    await manager.connect(ws)
    try:
        # Heartbeat loop. Client sends 'ping' or anything; we echo and broadcasts arrive concurrently.
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=25.0)
                if msg.strip().lower() == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Server-initiated heartbeat
                await ws.send_text(json.dumps({"type": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()}))
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
