"""Alert list/detail/triage endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..audit import ACTION_ALERT_TRIAGE, log_audit
from ..db import get_db
from ..models import Alert, AlertState, DeliveryState
from ..security import AuthContext, require_any

router = APIRouter(prefix="/alerts", tags=["alerts"])


class TriageRequest(BaseModel):
    state: str
    note: str | None = None


def _alert_dict(a: Alert, include_messages: bool = False) -> dict:
    d = {
        "id": a.id,
        "rule_id": a.rule_id,
        "rule_name": a.rule.name if a.rule else None,
        "rule_version": a.rule_version if a.rule_version is not None else (a.rule.version if a.rule else None),
        "source_id": a.source_id,
        "source_title": a.source.title if a.source else None,
        "severity": a.severity,
        "state": a.state,
        "excerpt": a.excerpt,
        "message_count": a.message_count,
        "first_seen_at": a.first_seen_at.isoformat() if a.first_seen_at else None,
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "delivery_state": a.delivery_state,
        "delivery_attempts": a.delivery_attempts,
        "last_delivery_error": a.last_delivery_error,
        "dedupe_window_seconds": a.dedup_window_seconds,
        "dedupe_closed_at": a.dedupe_closed_at.isoformat() if a.dedupe_closed_at else None,
        "triage_note": a.triage_note,
        "triaged_by": a.triaged_by,
        "triaged_at": a.triaged_at.isoformat() if a.triaged_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if include_messages:
        d["messages"] = [
            {
                "id": m.id,
                "telegram_message_id": m.telegram_message_id,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "text_preview": (m.original_text or "")[:500],
                "permalink": m.permalink,
                "state": m.state,
                "indicators": [
                    {"type": i.type, "value": i.value, "normalized_value": i.normalized_value}
                    for i in (m.indicators or [])
                ],
            }
            for m in a.messages
        ]
        d["deliveries"] = [
            {
                "attempt": dl.attempt,
                "status": dl.status,
                "status_code": dl.status_code,
                "error": dl.error,
                "attempted_at": dl.attempted_at.isoformat() if dl.attempted_at else None,
                "destination_type": dl.destination_type,
                "destination_ref": dl.destination_ref,
            }
            for dl in sorted(a.deliveries, key=lambda x: x.attempt)
        ]
    return d


@router.get("")
def list_alerts(
    ctx: AuthContext = Depends(require_any),
    db: Session = Depends(get_db),
    state: str | None = None,
    severity: str | None = None,
    rule_id: int | None = None,
    source_id: int | None = None,
    delivery_state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Alert).options(joinedload(Alert.rule), joinedload(Alert.source))
    if state:
        stmt = stmt.where(Alert.state == state)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if rule_id:
        stmt = stmt.where(Alert.rule_id == rule_id)
    if source_id:
        stmt = stmt.where(Alert.source_id == source_id)
    if delivery_state:
        stmt = stmt.where(Alert.delivery_state == delivery_state)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return {"items": [_alert_dict(a) for a in rows], "total": total}


@router.get("/{alert_id}")
def get_alert(alert_id: int, ctx: AuthContext = Depends(require_any), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return _alert_dict(a, include_messages=True)


@router.patch("/{alert_id}")
def triage_alert(
    alert_id: int,
    body: TriageRequest,
    ctx: AuthContext = Depends(require_any),
    db: Session = Depends(get_db),
):
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if body.state not in (AlertState.OPEN, AlertState.ACKNOWLEDGED, AlertState.RESOLVED, AlertState.FALSE_POSITIVE):
        raise HTTPException(status_code=400, detail="invalid alert state")
    from ..services.alerts_service import set_alert_triage

    set_alert_triage(db, a, body.state, body.note, ctx.user.username)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_ALERT_TRIAGE,
        object_type="alert",
        object_id=str(a.id),
        detail={"state": body.state, "note": bool(body.note)},
        ip_address=ctx.ip_address,
    )
    return _alert_dict(a, include_messages=True)
