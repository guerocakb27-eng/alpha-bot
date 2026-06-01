"""Shared test fixtures (Phase E2).

`test_db` swaps the app's module-level SessionLocal for one bound to a throwaway,
file-backed SQLite database with the full schema created, then patches every module
that imported SessionLocal BY NAME (execution_engine, sentiment_engine) so they use
the test session too. Keeps integration tests off the dev DB and isolated per test.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database.models as models


@pytest.fixture
def test_db(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    engine = create_engine(f"sqlite:///{tmp}", connect_args={"check_same_thread": False}, future=True)
    models.Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    # Rebind the canonical SessionLocal AND every by-name import of it.
    monkeypatch.setattr(models, "SessionLocal", TestSession)
    for mod in ("core.execution_engine", "core.sentiment_engine"):
        import importlib
        m = importlib.import_module(mod)
        if hasattr(m, "SessionLocal"):
            monkeypatch.setattr(m, "SessionLocal", TestSession)

    yield TestSession
    engine.dispose()
