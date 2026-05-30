"""add peak_r to trade (Phase B6 — persist trailing-stop peak across restarts)

Idempotent: adds the column only if missing, so it is safe on both an older DB
(created by create_all before peak_r existed) and a fresh DB (create_all already
includes it).

Revision ID: 0001_add_peak_r
Revises:
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_add_peak_r"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "trade"
COLUMN = "peak_r"


def _has_column() -> bool:
    insp = sa.inspect(op.get_bind())
    return COLUMN in {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    if not _has_column():
        op.add_column(TABLE, sa.Column(COLUMN, sa.Float(), server_default="0", nullable=False))


def downgrade() -> None:
    if _has_column():
        op.drop_column(TABLE, COLUMN)
