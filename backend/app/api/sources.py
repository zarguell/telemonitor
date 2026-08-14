"""Source allowlist + discovery endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import ACTION_SOURCE_ADD, ACTION_SOURCE_ENABLE, ACTION_SOURCE_PAUSE, ACTION_SOURCE_UPDATE, log_audit
from ..config import settings
from ..db import get_db
from ..jobs import TASK_BACKFILL_PAGE, enqueue
from ..models import BackfillMode, Source, SourceStatus, SourceType, TelegramConfiguration
from ..security import AuthContext, require_any, require_operator

router = APIRouter(prefix="/sources", tags=["sources"])


def _backfill_start(mode: str, custom: datetime | None = None) -> datetime | None:
    now = datetime.now(timezone.utc)
    if mode == BackfillMode.NONE:
        return None
    if mode == BackfillMode.HOURS_24:
        return now - timedelta(hours=24)
    if mode == BackfillMode.DAYS_7:
        return now - timedelta(days=7)
    if mode == BackfillMode.DAYS_30:
        return now - timedelta(days=30)
    if mode == BackfillMode.CUSTOM:
        return custom or (now - timedelta(days=7))
    return None


class SourceCreate(BaseModel):
    telegram_chat_id: int
    title: str
    username: str | None = None
    type: str = SourceType.CHANNEL
    label: str | None = None
    enabled: bool = True
    backfill: dict | None = None  # {mode: str, custom_start?: iso}


class SourcePatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    backfill: dict | None = None
    status: str | None = None


def _source_dict(s: Source) -> dict:
    return {
        "id": s.id,
        "telegram_chat_id": s.telegram_chat_id,
        "title": s.title,
        "username": s.username,
        "type": s.type,
        "enabled": s.enabled,
        "label": s.label,
        "status": s.status,
        "backfill_mode": s.backfill_mode,
        "backfill_start": s.backfill_start.isoformat() if s.backfill_start else None,
        "backfill_checkpoint": s.backfill_checkpoint,
        "backfill_total": s.backfill_total,
        "backfill_done": s.backfill_done,
        "backfill_progress": round(100 * s.backfill_done / s.backfill_total, 1)
        if s.backfill_total
        else None,
        "backfill_error": s.backfill_error,
        "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
        "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
        "last_error": s.last_error,
        "allowlisted_at": s.allowlisted_at.isoformat() if s.allowlisted_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/discovered")
async def discovered(ctx: AuthContext = Depends(require_operator), db: Session = Depends(get_db)):
    """List chats/channels visible to the authorized account (no auto-enable)."""
    url = f"{settings.collector_control_url.rstrip('/')}/control/dialogs"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, headers={"X-Control-Token": settings.collector_control_token})
        if r.status_code == 409:
            raise HTTPException(status_code=409, detail=r.json().get("detail", "not authorized"))
        r.raise_for_status()
        dialogs = r.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Collector is unreachable: {e}")

    allowlisted = {
        s.telegram_chat_id: s for s in db.scalars(select(Source)).all()
    }
    out = []
    for d in dialogs:
        s = allowlisted.get(d["chat_id"])
        out.append(
            {
                **d,
                "allowlisted": s is not None,
                "monitored_id": s.id if s else None,
                "enabled": s.enabled if s else False,
                "label": s.label if s else None,
            }
        )
    return out


@router.get("")
def list_sources(ctx: AuthContext = Depends(require_any), db: Session = Depends(get_db)):
    sources = db.scalars(select(Source).order_by(Source.title)).all()
    return {"items": [_source_dict(s) for s in sources], "total": len(sources)}


@router.post("")
async def create_source(
    body: SourceCreate,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(Source).where(Source.telegram_chat_id == body.telegram_chat_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Source {body.telegram_chat_id} is already allowlisted")
    bf = body.backfill or {}
    mode = bf.get("mode", BackfillMode.NONE)
    if mode not in (BackfillMode.NONE, BackfillMode.HOURS_24, BackfillMode.DAYS_7, BackfillMode.DAYS_30, BackfillMode.CUSTOM):
        raise HTTPException(status_code=400, detail=f"invalid backfill mode: {mode}")
    custom = None
    if mode == BackfillMode.CUSTOM:
        try:
            custom = datetime.fromisoformat(bf["custom_start"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="custom_start must be an ISO-8601 timestamp")
        if custom > datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="custom_start cannot be in the future")

    source = Source(
        telegram_chat_id=body.telegram_chat_id,
        title=body.title,
        username=body.username,
        type=body.type,
        enabled=body.enabled,
        label=body.label,
        allowlisted_at=datetime.now(timezone.utc),
        backfill_mode=mode,
        backfill_start=_backfill_start(mode, custom),
    )
    if body.enabled and mode != BackfillMode.NONE:
        source.status = SourceStatus.BACKFILLING
    else:
        source.status = SourceStatus.LIVE if body.enabled else SourceStatus.PAUSED
    db.add(source)
    db.commit()
    db.refresh(source)
    if source.status == SourceStatus.BACKFILLING:
        enqueue(TASK_BACKFILL_PAGE, source_id=source.id)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_SOURCE_ADD,
        object_type="source",
        object_id=str(source.id),
        detail={"chat_id": body.telegram_chat_id, "title": body.title, "backfill": mode},
        ip_address=ctx.ip_address,
    )
    return _source_dict(source)


@router.patch("/{source_id}")
async def patch_source(
    source_id: int,
    body: SourcePatch,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    actions: list[str] = []
    if body.enabled is not None and body.enabled != source.enabled:
        source.enabled = body.enabled
        actions.append(ACTION_SOURCE_ENABLE if body.enabled else ACTION_SOURCE_PAUSE)
        if body.enabled:
            if source.backfill_mode != BackfillMode.NONE and source.backfill_checkpoint is None:
                source.status = SourceStatus.BACKFILLING
                enqueue(TASK_BACKFILL_PAGE, source_id=source.id)
            else:
                source.status = SourceStatus.LIVE
        else:
            source.status = SourceStatus.PAUSED
    if body.label is not None:
        source.label = body.label
    if body.status is not None and body.status in (SourceStatus.LIVE, SourceStatus.PAUSED, SourceStatus.ERROR):
        source.status = body.status
    if body.backfill is not None:
        mode = body.backfill.get("mode", source.backfill_mode)
        custom = None
        if mode == BackfillMode.CUSTOM and body.backfill.get("custom_start"):
            custom = datetime.fromisoformat(body.backfill["custom_start"].replace("Z", "+00:00"))
        source.backfill_mode = mode
        source.backfill_start = _backfill_start(mode, custom)
        source.backfill_checkpoint = None
        source.backfill_done = 0
        source.backfill_total = None
        source.backfill_error = None
        if source.enabled and mode != BackfillMode.NONE:
            source.status = SourceStatus.BACKFILLING
            enqueue(TASK_BACKFILL_PAGE, source_id=source.id)
    db.commit()
    db.refresh(source)
    for action in actions:
        log_audit(
            db,
            actor_user_id=ctx.user.id,
            actor_username=ctx.user.username,
            action=action,
            object_type="source",
            object_id=str(source.id),
            detail={"title": source.title},
            ip_address=ctx.ip_address,
        )
    if body.backfill is not None:
        log_audit(
            db,
            actor_user_id=ctx.user.id,
            actor_username=ctx.user.username,
            action=ACTION_SOURCE_UPDATE,
            object_type="source",
            object_id=str(source.id),
            detail={"backfill_mode": source.backfill_mode},
            ip_address=ctx.ip_address,
        )
    return _source_dict(source)


@router.delete("/{source_id}")
async def delete_source(
    source_id: int,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    db.delete(source)
    db.commit()
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_SOURCE_UPDATE,
        object_type="source",
        object_id=str(source_id),
        detail={"deleted": True, "title": source.title},
        ip_address=ctx.ip_address,
    )
    return {"ok": True}
