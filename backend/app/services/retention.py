"""Retention: delete expired message content and dependent records."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    AlertMessage,
    Indicator,
    Message,
    MessageEvent,
    RuleMatch,
)

logger = logging.getLogger(__name__)


def delete_expired(db: Session, cutoff: datetime) -> int:
    """Delete messages older than cutoff (and their indicators, matches, events).

    Preserves alerts (triage metadata) but removes their message links.
    """
    ids = list(
        db.scalars(
            select(Message.id).where(
                (Message.sent_at.is_(None) & (Message.ingested_at < cutoff))
                | (Message.sent_at < cutoff)
            ).limit(10000)
        )
    )
    if not ids:
        return 0
    db.execute(delete(AlertMessage).where(AlertMessage.message_id.in_(ids)))
    db.execute(delete(Indicator).where(Indicator.message_id.in_(ids)))
    db.execute(delete(RuleMatch).where(RuleMatch.message_id.in_(ids)))
    db.execute(delete(MessageEvent).where(MessageEvent.message_id.in_(ids)))
    result = db.execute(delete(Message).where(Message.id.in_(ids)))
    db.commit()
    count = result.rowcount or 0
    logger.info("retention deleted messages", extra={"count": count, "cutoff": cutoff.isoformat()})
    return count


def count_retained(db: Session, cutoff: datetime) -> int:
    return db.scalar(select(func.count(Message.id)).where(Message.sent_at >= cutoff)) or 0
