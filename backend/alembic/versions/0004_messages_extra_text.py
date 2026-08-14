"""Add messages.extra_text for entity-only URLs (Telegram link previews).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS extra_text TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS extra_text")
