"""Webhook HMAC validation + simple in-memory rate limiting."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from config import settings


# ─── HMAC ────────────────────────────────────────────────────────────
def verify_signature(payload: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against WEBHOOK_SECRET.

    Accepts headers in the form 'sha256=<hex>' or raw hex.
    """
    if not signature_header or not settings.webhook_secret:
        return False
    provided = signature_header.split("=", 1)[1] if "=" in signature_header else signature_header
    expected = hmac.new(settings.webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.lower())


# ─── Rate Limiter ────────────────────────────────────────────────────
class RateLimiter:
    """Per-IP sliding-window counter. In-memory; reset on process restart."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self.max = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, ip: str) -> bool:
        now = time.monotonic()
        q = self._hits[ip]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.max:
            return False
        q.append(now)
        return True


webhook_limiter = RateLimiter(max_requests=60, window_seconds=60)


def require_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    if not webhook_limiter.check(ip):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
