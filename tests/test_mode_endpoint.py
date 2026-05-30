"""Phase B2 — the /bot/mode endpoint must refuse a LIVE switch unless
ENABLE_LIVE_TRADING is set (defense in depth on top of the engine gate)."""
from __future__ import annotations

import warnings

import pytest
from fastapi import HTTPException

import api.routes.status as st

warnings.filterwarnings("ignore")


def test_switch_to_live_blocked_without_flag(monkeypatch):
    monkeypatch.setattr(st.repository, "log_event", lambda *a, **k: None)
    orig = st.bot_state.mode
    try:
        st.settings.enable_live_trading = False
        with pytest.raises(HTTPException) as ei:
            st.change_mode(st.ModeChange(mode="LIVE", confirm_live=True), db=None)
        assert ei.value.status_code == 400
        assert st.bot_state.mode == orig  # mode must not change on rejection
    finally:
        st.bot_state.mode = orig


def test_switch_to_live_allowed_with_flag(monkeypatch):
    monkeypatch.setattr(st.repository, "log_event", lambda *a, **k: None)
    orig = st.bot_state.mode
    try:
        st.settings.enable_live_trading = True
        out = st.change_mode(st.ModeChange(mode="LIVE", confirm_live=True), db=None)
        assert out["mode"] == "LIVE"
    finally:
        st.bot_state.mode = orig
        st.settings.enable_live_trading = False


def test_switch_to_paper_always_allowed(monkeypatch):
    monkeypatch.setattr(st.repository, "log_event", lambda *a, **k: None)
    orig = st.bot_state.mode
    try:
        st.settings.enable_live_trading = False
        out = st.change_mode(st.ModeChange(mode="PAPER", confirm_live=False), db=None)
        assert out["mode"] == "PAPER"
    finally:
        st.bot_state.mode = orig
