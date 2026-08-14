"""Token versioning (session revocation) and alert rule-version snapshot.

- users.token_version: incremented on logout/password change; JWTs embed the
  version at issue time and require_auth rejects older tokens.
- alerts.rule_version: snapshot of the rule version when the alert was created
  (previously the current rule version was read at read/delivery time).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS rule_version INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS rule_version")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
