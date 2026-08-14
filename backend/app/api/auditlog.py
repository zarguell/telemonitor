"""Audit log listing (Administrators and Operators)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..audit import list_audit
from ..db import get_db
from ..security import AuthContext, require_operator

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def audit_log(
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    rows, total = list_audit(
        db,
        actor=actor,
        action=action,
        object_type=object_type,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "id": e.id,
                "actor_username": e.actor_username,
                "action": e.action,
                "object_type": e.object_type,
                "object_id": e.object_id,
                "detail": e.detail,
                "ip_address": e.ip_address,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ],
        "total": total,
    }
