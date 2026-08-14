"""Global settings (Administrators only): retention, alert destination, aliases."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import ACTION_DESTINATION_TEST, ACTION_SETTINGS_UPDATE, get_setting, log_audit, set_setting
from ..crypto import encrypt_secret
from ..db import get_db
from ..security import AuthContext, require_admin
from ..services.delivery import destination_summary, test_destination

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


class DestinationModel(BaseModel):
    type: str = "none"  # none | webhook | telegram_bot
    url: str | None = None
    token: str | None = None  # bot token (plaintext only on save; stored encrypted)
    chat_id: str | None = None


class MediaSettings(BaseModel):
    store_media: bool = False


class SettingsUpdate(BaseModel):
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    alert_destination: DestinationModel | None = None
    aliases: list[dict] | None = None  # [{"alias": ..., "canonical": ...}]
    media_settings: MediaSettings | None = None


@router.get("")
def get_settings(ctx: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    retention = get_setting(db, "retention_days", {}) or {}
    dest = get_setting(db, "alert_destination", {}) or {}
    aliases = get_setting(db, "aliases", {}) or {}
    media = get_setting(db, "media_settings", {}) or {}
    return {
        "retention_days": int(retention.get("days", 90)),
        "alert_destination": destination_summary(dest),
        "aliases": aliases.get("items", []),
        "media_settings": {"store_media": bool((media or {}).get("store_media"))},
    }


@router.put("")
def update_settings(
    body: SettingsUpdate,
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    changed: list[str] = []
    if body.retention_days is not None:
        set_setting(db, "retention_days", {"days": body.retention_days}, ctx.user.username)
        changed.append("retention_days")
    if body.aliases is not None:
        cleaned = [a for a in body.aliases if isinstance(a, dict) and a.get("alias")]
        set_setting(db, "aliases", {"items": cleaned}, ctx.user.username)
        changed.append("aliases")
    if body.media_settings is not None:
        set_setting(
            db,
            "media_settings",
            {"store_media": body.media_settings.store_media},
            ctx.user.username,
        )
        changed.append("media_settings")
    if body.alert_destination is not None:
        d = body.alert_destination
        if d.type not in ("none", "webhook", "telegram_bot"):
            raise HTTPException(status_code=400, detail="type must be none|webhook|telegram_bot")
        if d.type == "webhook":
            if not d.url:
                raise HTTPException(status_code=400, detail="webhook url required (http/https)")
            from ..services.delivery import validate_webhook_url

            try:
                validate_webhook_url(d.url)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            dest = {"type": "webhook", "url": d.url}
        elif d.type == "telegram_bot":
            if not d.token or not d.chat_id:
                raise HTTPException(status_code=400, detail="bot token and chat_id required")
            dest = {"type": "telegram_bot", "token_enc": encrypt_secret(d.token), "chat_id": d.chat_id}
        else:
            dest = {"type": "none"}
        set_setting(db, "alert_destination", dest, ctx.user.username)
        changed.append("alert_destination")
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_SETTINGS_UPDATE,
        object_type="settings",
        detail={"changed": changed},
        ip_address=ctx.ip_address,
    )
    return get_settings(ctx=ctx, db=db)


@router.post("/destination/test")
def test_destination_endpoint(
    ctx: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dest = get_setting(db, "alert_destination", {}) or {}
    if not dest or dest.get("type") in (None, "none"):
        raise HTTPException(status_code=400, detail="no alert destination configured")
    result = test_destination(db, dest)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_DESTINATION_TEST,
        object_type="settings",
        detail={"ok": result.get("ok"), "type": dest.get("type")},
        ip_address=ctx.ip_address,
    )
    return result
