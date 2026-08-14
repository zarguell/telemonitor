"""Search endpoint: full-text + substring over normalized_text with filters."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from ..audit import ACTION_SEARCH, log_audit
from ..db import get_db
from ..models import (
    Alert,
    AlertMessage,
    Indicator,
    Message,
    MessageState,
    RuleMatch,
    Source,
)
from ..redact import redact_text
from ..security import AuthContext, require_any
from ..services.normalize import highlight_snippet, normalize_text

router = APIRouter(prefix="/search", tags=["search"])

MAX_LIMIT = 200


def _build_query(
    q: str | None,
    source_id: int | None,
    start_time: datetime | None,
    end_time: datetime | None,
    rule_id: int | None,
    alert_state: str | None,
    indicator_type: str | None,
    message_state: str | None,
):
    stmt = select(Message).join(Message.source)
    if q:
        needle = normalize_text(q)
        stmt = stmt.where(
            or_(
                # autoescape=True treats %/_/\ in the query literally
                Message.normalized_text.contains(needle, autoescape=True),
                func.to_tsvector("simple", func.coalesce(Message.normalized_text, "")).op("@@")(  # type: ignore[attr-defined]
                    func.plainto_tsquery("simple", needle)
                ),
            )
        )
    if source_id is not None:
        stmt = stmt.where(Message.source_id == source_id)
    if start_time:
        stmt = stmt.where(Message.sent_at >= start_time)
    if end_time:
        stmt = stmt.where(Message.sent_at <= end_time)
    if message_state:
        stmt = stmt.where(Message.state == message_state)
    if rule_id:
        stmt = stmt.where(Message.id.in_(select(RuleMatch.message_id).where(RuleMatch.rule_id == rule_id)))
    if alert_state:
        stmt = stmt.where(
            Message.id.in_(
                select(AlertMessage.message_id)
                .join(Alert, Alert.id == AlertMessage.alert_id)
                .where(Alert.state == alert_state)
            )
        )
    if indicator_type:
        stmt = stmt.where(
            Message.id.in_(select(Indicator.message_id).where(Indicator.type == indicator_type))
        )
    return stmt


@router.get("")
def search(
    ctx: AuthContext = Depends(require_any),
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, max_length=500),
    source_id: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    rule_id: int | None = None,
    alert_state: str | None = None,
    indicator_type: str | None = None,
    message_state: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    stmt = _build_query(
        q, source_id, start_time, end_time, rule_id, alert_state, indicator_type, message_state
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.options(
                selectinload(Message.indicators),
                selectinload(Message.rule_matches),
                selectinload(Message.alerts),
            )
            .order_by(Message.sent_at.desc().nullslast(), Message.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )

    alert_states: dict[int, list[dict]] = {}
    if rows:
        alert_rows = db.execute(
            select(AlertMessage.message_id, Alert.id, Alert.state, Alert.severity)
            .join(Alert, Alert.id == AlertMessage.alert_id)
            .where(AlertMessage.message_id.in_([m.id for m in rows]))
        ).all()
        for mid, aid, state, sev in alert_rows:
            alert_states.setdefault(mid, []).append({"id": aid, "state": state, "severity": sev})

    items = []
    for m in rows:
        snippet = highlight_snippet(m.original_text, q)
        items.append(
            {
                "id": m.id,
                "source_id": m.source_id,
                "source_name": m.source.title,
                "source_username": m.source.username,
                "source_status": m.source.status,
                "telegram_message_id": m.telegram_message_id,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "ingested_at": m.ingested_at.isoformat() if m.ingested_at else None,
                "edited_at": m.edited_at.isoformat() if m.edited_at else None,
                "state": m.state,
                "snippet": snippet,
                "text_preview": (m.original_text or "")[:300],
                "normalized_text": (m.normalized_text or "")[:500],
                "indicators": [
                    {
                        "type": i.type,
                        "value": i.value,
                        "normalized_value": i.normalized_value,
                        "confidence": i.confidence,
                    }
                    for i in (m.indicators or [])
                ],
                "rule_matches": [
                    {"rule_id": rm.rule_id, "rule_version": rm.rule_version, "matched_at": rm.matched_at.isoformat() if rm.matched_at else None}
                    for rm in (m.rule_matches or [])
                ],
                "alerts": alert_states.get(m.id, []),
                "permalink": m.permalink,
                "reply_to_msg_id": m.reply_to_msg_id,
                "forward_from_name": m.forward_from_name,
                "sender_id": m.sender_id,
                "media_type": m.media_type,
                "media_stored": m.media_stored,
                "media_filename": m.media_filename,
                "media_content_type": m.media_content_type,
            }
        )
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_SEARCH,
        detail={
            "q": redact_text(q or ""),
            "source_id": source_id,
            "indicator_type": indicator_type,
            "result_count": total,
        },
        ip_address=ctx.ip_address,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}
