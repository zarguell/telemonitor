"""Add media_attempts (download retry cap).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_attempts INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS media_attempts")
