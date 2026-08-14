"""Drop the unique constraint on alerts.dedupe_key.

Dedupe keys are intentionally non-unique: once a rule's window elapses, the same
key legitimately starts a NEW alert. Deduplication is enforced by the lookup in
create_alert_candidate, not by the database.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_dedupe_key_key")
    op.execute("CREATE INDEX IF NOT EXISTS ix_alerts_dedupe_key ON alerts (dedupe_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_alerts_dedupe_key")
    op.execute("ALTER TABLE alerts ADD CONSTRAINT alerts_dedupe_key_key UNIQUE (dedupe_key)")
