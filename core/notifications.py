"""Notification manager — Telegram, Discord, Email. All channels optional.

Channels with empty credentials are silently skipped. Global 1-message-per-5s
rate limit prevents spam during noisy periods.
"""
from __future__ import annotations

import asyncio
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any

import httpx
from loguru import logger

from config import settings
from database.models import Trade


_RATE_LIMIT_INTERVAL = 5.0


class NotificationManager:
    """Singleton-ish — instantiate once in app startup, call from anywhere."""

    def __init__(self) -> None:
        self._last_send: float = 0.0
        self._lock = asyncio.Lock()

    # ─── Channel implementations ──────────────────────────────────────
    async def _send_telegram(self, text: str) -> None:
        if not (settings.telegram_bot_token and settings.telegram_chat_id):
            return
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(url, json={
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
        except Exception as e:
            logger.warning("Telegram send failed: {}", e)

    async def _send_discord(self, text: str) -> None:
        if not settings.discord_webhook_url:
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(settings.discord_webhook_url, json={"content": text})
        except Exception as e:
            logger.warning("Discord send failed: {}", e)

    def _send_email_sync(self, subject: str, body: str) -> None:
        # SMTP details not wired into Settings yet — Phase 8 deploy work.
        return

    # ─── Public API ───────────────────────────────────────────────────
    async def send(self, text: str, channels: list[str] | None = None) -> None:
        """Send to all enabled channels, respecting rate limit."""
        async with self._lock:
            now = time.monotonic()
            wait = _RATE_LIMIT_INTERVAL - (now - self._last_send)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_send = time.monotonic()

        channels = channels or ["telegram", "discord"]
        tasks: list[Any] = []
        if "telegram" in channels:
            tasks.append(self._send_telegram(text))
        if "discord" in channels:
            tasks.append(self._send_discord(text))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ─── Convenience event formatters ─────────────────────────────────
    async def trade_opened(self, trade: Trade) -> None:
        side = trade.side.value if hasattr(trade.side, "value") else trade.side
        emoji = "🟢" if side == "BUY" else "🔴"
        text = (
            f"{emoji} *Trade Opened*\n"
            f"`{trade.symbol}` *{side}* @ `{trade.entry_price:.4f}`\n"
            f"Qty: `{trade.quantity:.6f}`\n"
            f"SL: `{trade.stop_loss:.4f}` | TP: `{trade.take_profit:.4f}`\n"
            f"Score: `{trade.signal_score:+d}` | Regime: `{trade.market_regime}`"
        )
        await self.send(text)

    async def trade_closed(self, trade: Trade, reason: str) -> None:
        side = trade.side.value if hasattr(trade.side, "value") else trade.side
        win = trade.pnl_usdt > 0
        emoji = "✅" if win else "❌"
        duration = ""
        if trade.entry_time and trade.exit_time:
            from datetime import timezone as _tz
            et = trade.entry_time.replace(tzinfo=_tz.utc) if trade.entry_time.tzinfo is None else trade.entry_time
            xt = trade.exit_time.replace(tzinfo=_tz.utc) if trade.exit_time.tzinfo is None else trade.exit_time
            secs = (xt - et).total_seconds()
            duration = f"\nDuration: `{int(secs / 60)}m`"
        text = (
            f"{emoji} *Trade Closed* ({reason})\n"
            f"`{trade.symbol}` *{side}* @ `{trade.exit_price:.4f}`\n"
            f"PnL: `${trade.pnl_usdt:+.2f}` ({trade.pnl_pct:+.2f}%)"
            f"{duration}"
        )
        await self.send(text)

    async def daily_summary(self, stats: dict) -> None:
        text = (
            f"📊 *Daily Summary*\n"
            f"Trades: `{stats.get('trades', 0)}`  Win rate: `{stats.get('win_rate', 0):.1f}%`\n"
            f"PnL: `${stats.get('pnl_usdt', 0):+.2f}` ({stats.get('pnl_pct', 0):+.2f}%)\n"
            f"Best: `${stats.get('best', 0):+.2f}`  Worst: `${stats.get('worst', 0):+.2f}`"
        )
        await self.send(text)

    async def error(self, message: str, critical: bool = False) -> None:
        prefix = "🚨" if critical else "⚠️"
        await self.send(f"{prefix} *Error*\n{message}")

    async def optimization_complete(self, old_sharpe: float, new_sharpe: float, applied: bool) -> None:
        emoji = "✨" if applied else "🔬"
        verdict = "*Applied*" if applied else "_Not applied (improvement too small)_"
        text = (
            f"{emoji} *Optimization Complete*\n"
            f"Old Sharpe: `{old_sharpe:.2f}` → New Sharpe: `{new_sharpe:.2f}`\n"
            f"{verdict}"
        )
        await self.send(text)


notifications = NotificationManager()
