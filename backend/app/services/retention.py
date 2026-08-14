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
    rows = list(
        db.execute(
            select(Message.id, Message.media_sha256)
            .where(
                (Message.sent_at.is_(None) & (Message.ingested_at < cutoff))
                | (Message.sent_at < cutoff)
            )
            .limit(10000)
        ).all()
    )
    if not rows:
        return 0
    ids = [r.id for r in rows]
    db.execute(delete(AlertMessage).where(AlertMessage.message_id.in_(ids)))
    db.execute(delete(Indicator).where(Indicator.message_id.in_(ids)))
    db.execute(delete(RuleMatch).where(RuleMatch.message_id.in_(ids)))
    db.execute(delete(MessageEvent).where(MessageEvent.message_id.in_(ids)))
    result = db.execute(delete(Message).where(Message.id.in_(ids)))
    db.commit()
    count = result.rowcount or 0
    # MEDIA-03: purge media objects ONLY after the DB commit, and only when no
    # surviving message still references the same content digest (media is
    # content-addressed, so two messages may share one file).
    from .storage import MediaStoreError, get_media_store

    store = None
    for _id, digest in rows:
        if not digest:
            continue
        try:
            still_referenced = db.scalar(
                select(Message.id).where(Message.media_sha256 == digest).limit(1)
            )
        except Exception:  # noqa: BLE001
            still_referenced = True
        if still_referenced:
            continue
        try:
            if store is None:
                store = get_media_store()
            store.delete(digest)
        except (MediaStoreError, Exception):  # noqa: BLE001
            logger.debug("media purge skipped", extra={"sha": digest[:12]})
    logger.info("retention deleted messages", extra={"count": count, "cutoff": cutoff.isoformat()})
    return count


def count_retained(db: Session, cutoff: datetime) -> int:
    return db.scalar(select(func.count(Message.id)).where(Message.sent_at >= cutoff)) or 0
