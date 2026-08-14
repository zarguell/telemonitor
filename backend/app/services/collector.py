"""Message persistence from the Telegram layer.

All writes are idempotent on (source_id, telegram_message_id). The collector's
event handler persists quickly here and defers heavy processing to the realtime queue.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..jobs import TASK_REALTIME_PROCESS, enqueue
from ..models import EventType, Message, MessageEvent, MessageState, Source
from .normalize import normalize_text

logger = logging.getLogger(__name__)


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get_source(db: Session, chat_id: int) -> Source | None:
    return db.scalar(select(Source).where(Source.telegram_chat_id == chat_id))


def persist_message(db: Session, m: dict) -> Message | None:
    """Idempotent write of one Telegram message dict.

    Returns None when the source is not enabled in the allowlist (allowlist enforcement).
    """
    source = _get_source(db, m["chat_id"])
    if source is None or not source.enabled:
        logger.debug("ignoring message from non-allowlisted source", extra={"chat_id": m["chat_id"]})
        return None

    existing = db.scalar(
        select(Message).where(
            Message.source_id == source.id,
            Message.telegram_message_id == int(m["id"]),
        )
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        if m.get("edit_date") and m.get("text") != existing.original_text:
            existing.original_text = m.get("text")
            existing.normalized_text = normalize_text(m.get("text"))
            existing.edited_at = m.get("edit_date")
            existing.content_hash = content_hash(m.get("text"))
            db.add(MessageEvent(message_id=existing.id, event_type=EventType.EDITED, detail={"edited_at": m.get("edit_date").isoformat() if m.get("edit_date") else None}))
            db.commit()
            enqueue(TASK_REALTIME_PROCESS, message_id=existing.id)
            logger.info("message edited", extra={"message_id": existing.id})
        return existing

    msg = Message(
        source_id=source.id,
        telegram_message_id=int(m["id"]),
        sent_at=m.get("date"),
        ingested_at=now,
        edited_at=m.get("edit_date"),
        original_text=m.get("text"),
        normalized_text=normalize_text(m.get("text")),
        sender_id=m.get("sender_id"),
        reply_to_msg_id=m.get("reply_to_msg_id"),
        forward_from_id=m.get("forward_from_id"),
        forward_from_name=m.get("forward_from_name"),
        media_type=m.get("media_type"),
        media_metadata=m.get("media_meta"),
        state=MessageState.PENDING,
        content_hash=content_hash(m.get("text")),
        permalink=m.get("permalink"),
    )
    db.add(msg)
    db.flush()
    db.add(MessageEvent(message_id=msg.id, event_type=EventType.CREATED, detail={"ingested_at": now.isoformat()}))
    db.commit()
    logger.info("message persisted", extra={"message_id": msg.id, "source_id": source.id})
    return msg


def handle_new_message(m: dict) -> None:
    """Called by the collector event handler: persist quickly, then defer."""
    db = None
    try:
        from ..db import db_session

        db = db_session()
        msg = persist_message(db, m)
        if msg is not None:
            enqueue(TASK_REALTIME_PROCESS, message_id=msg.id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to persist incoming message", extra={"chat_id": m.get("chat_id"), "id": m.get("id")})
    finally:
        if db is not None:
            db.close()


def handle_message_edit(chat_id: int, message_id: int, text: str | None, edit_date: datetime | None = None) -> None:
    db = None
    try:
        from ..db import db_session

        db = db_session()
        source = _get_source(db, chat_id)
        if source is None:
            return
        msg = db.scalar(
            select(Message).where(
                Message.source_id == source.id,
                Message.telegram_message_id == message_id,
            )
        )
        if msg is None or msg.original_text == text:
            return
        msg.original_text = text
        msg.normalized_text = normalize_text(text)
        msg.edited_at = edit_date or datetime.now(timezone.utc)
        msg.content_hash = content_hash(text)
        msg.state = MessageState.PENDING
        db.add(MessageEvent(message_id=msg.id, event_type=EventType.EDITED))
        db.commit()
        enqueue(TASK_REALTIME_PROCESS, message_id=msg.id)
    finally:
        if db is not None:
            db.close()


def handle_message_delete(chat_id: int, message_ids: list[int]) -> None:
    db = None
    try:
        from ..db import db_session

        db = db_session()
        source = _get_source(db, chat_id)
        if source is None:
            return
        for mid in message_ids:
            msg = db.scalar(
                select(Message).where(
                    Message.source_id == source.id,
                    Message.telegram_message_id == mid,
                )
            )
            if msg is None:
                continue
            msg.state = MessageState.DELETED
            db.add(MessageEvent(message_id=msg.id, event_type=EventType.DELETED))
            logger.info("message marked deleted", extra={"message_id": msg.id})
        db.commit()
    finally:
        if db is not None:
            db.close()
