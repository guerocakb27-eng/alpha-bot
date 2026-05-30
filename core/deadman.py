"""Dead-man's switch detection (Phase B8).

Pure predicate so the trigger condition is trivially testable; the engine owns
the contact timestamp and the alert/flatten action.
"""
from __future__ import annotations


def deadman_triggered(last_contact: float, now: float, timeout_s: float) -> bool:
    """True if the time since the last successful exchange contact exceeds the timeout."""
    return (now - last_contact) > timeout_s
