"""Media storage columns on messages.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_sha256 TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_content_type TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_size_bytes BIGINT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_filename TEXT")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS media_stored BOOLEAN NOT NULL DEFAULT FALSE")


def downgrade() -> None:
    for col in ("media_stored", "media_filename", "media_size_bytes", "media_content_type", "media_sha256"):
        op.execute(f"ALTER TABLE messages DROP COLUMN IF EXISTS {col}")
