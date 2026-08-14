"""Initial schema: all entities, search indexes, and seed data.

Revision ID: 0001
Revises:
Create Date: 2026-08-13
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    from app import models  # noqa: F401
    from app.config import settings
    from app.db import Base
    from sqlalchemy import text

    Base.metadata.create_all(bind=bind)

    # Full-text + trigram search indexes over normalized_text
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_fts ON messages "
        "USING gin (to_tsvector('simple', coalesce(normalized_text, '')))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_trgm ON messages "
        "USING gin (normalized_text gin_trgm_ops)"
    )

    # --- Seeds ---
    # No user accounts are seeded here: the initial administrator is created
    # at application startup from TM_SEED_ADMIN_PASSWORD (no default exists).
    now = datetime.now(timezone.utc).isoformat()

    bind.execute(
        text(
            "INSERT INTO telegram_configuration (id, status, created_at, updated_at) "
            "VALUES (1, 'not_configured', :now, :now) ON CONFLICT (id) DO NOTHING"
        ),
        {"now": now},
    )

    settings_rows = [
        ("retention_days", {"days": settings.default_retention_days}),
        ("alert_destination", {"type": "none"}),
        ("aliases", {"items": []}),
    ]
    for key, value in settings_rows:
        bind.execute(
            text(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (:key, CAST(:value AS jsonb), :now) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": json.dumps(value), "now": now},
        )


def downgrade() -> None:
    bind = op.get_bind()
    from app.db import Base

    for table in reversed(Base.metadata.sorted_tables):
        bind.execute(f"DROP TABLE IF EXISTS {table.name} CASCADE")
