"""Telegram configuration endpoints (Operators/Administrators only).

All secrets are handled by the collector in memory; this API only forwards
transient values over the private control channel and never stores them.
"""
from __future__ import annotations

import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import (
    ACTION_TELEGRAM_2FA_SUBMITTED,
    ACTION_TELEGRAM_CODE_SUBMITTED,
    ACTION_TELEGRAM_CONNECT,
    ACTION_TELEGRAM_DISCONNECT,
    ACTION_TELEGRAM_INIT,
    ACTION_TELEGRAM_PHONE,
    log_audit,
)
from ..config import settings
from ..db import get_db
from ..models import TelegramConfiguration
from ..redact import redact_text
from ..security import AuthContext, require_operator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])

_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_API_ID_RE = re.compile(r"^\d{5,9}$")
_API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class InitializeRequest(BaseModel):
    api_id: str
    api_hash: str
    acknowledgement: bool = Field(..., description="Operator confirms authorization to use the account")


class PhoneRequest(BaseModel):
    phone: str


class CodeRequest(BaseModel):
    code: str


class PasswordRequest(BaseModel):
    password: str


class DisconnectRequest(BaseModel):
    confirm: bool = False


async def _control(path: str, **body) -> dict:
    """Forward a request to the collector's internal control API."""
    url = f"{settings.collector_control_url.rstrip('/')}/control/{path}"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                url,
                json=body,
                headers={"X-Control-Token": settings.collector_control_token},
            )
        if r.status_code == 401:
            raise HTTPException(status_code=503, detail="Collector rejected control token")
        if r.status_code == 503:
            raise HTTPException(status_code=503, detail="Collector service not ready")
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as e:
        logger.warning("collector control call failed", extra={"path": path, "error": str(e)})
        raise HTTPException(status_code=503, detail="Collector is unreachable")


@router.get("/status")
def telegram_status(ctx: AuthContext = Depends(require_operator), db: Session = Depends(get_db)):
    cfg = db.get(TelegramConfiguration, 1)
    if cfg is None:
        return {
            "state": "not_configured",
            "detail": None,
            "error": None,
            "connected_account": None,
            "simulated": settings.simulate_telegram,
        }
    return {
        "state": cfg.status,
        "detail": cfg.status_detail,
        "error": cfg.last_error,
        "connected_account": cfg.connected_account,
        "last_update": cfg.last_update_at.isoformat() if cfg.last_update_at else None,
        "collector_heartbeat": cfg.collector_heartbeat_at.isoformat() if cfg.collector_heartbeat_at else None,
        "simulated": settings.simulate_telegram,
        "encryption_key_fingerprint": cfg.session_key_ref,
    }


@router.post("/initialize")
async def telegram_initialize(
    body: InitializeRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not body.acknowledgement:
        raise HTTPException(
            status_code=400,
            detail="You must acknowledge that you are authorized to use this account and "
            "have reviewed applicable platform, privacy, and organizational requirements.",
        )
    if not _API_ID_RE.match(body.api_id):
        raise HTTPException(status_code=400, detail="API ID must be a numeric application identifier (5-9 digits)")
    if not _API_HASH_RE.match(body.api_hash):
        raise HTTPException(status_code=400, detail="API hash must be a 32-character hexadecimal string")
    result = await _control("initialize", api_id=body.api_id, api_hash=body.api_hash)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_INIT,
        object_type="telegram_configuration",
        object_id="1",
        ip_address=ctx.ip_address,
    )
    return result


@router.post("/phone")
async def telegram_phone(
    body: PhoneRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not _PHONE_RE.match(body.phone):
        raise HTTPException(status_code=400, detail="Phone must be in E.164 format (e.g. +15551234567)")
    result = await _control("phone", phone=body.phone)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_PHONE,
        object_type="telegram_configuration",
        object_id="1",
        detail={"phone_country_code": body.phone[:3]},  # never the full number
        ip_address=ctx.ip_address,
    )
    return result


@router.post("/code")
async def telegram_code(
    body: CodeRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="Code required")
    result = await _control("code", code=body.code)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_CODE_SUBMITTED,
        object_type="telegram_configuration",
        object_id="1",
        detail={"code_length": len(body.code)},  # never the code
        ip_address=ctx.ip_address,
    )
    return result


@router.post("/password")
async def telegram_password(
    body: PasswordRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not body.password:
        raise HTTPException(status_code=400, detail="Password required")
    result = await _control("password", password=body.password)
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_2FA_SUBMITTED,
        object_type="telegram_configuration",
        object_id="1",
        ip_address=ctx.ip_address,
    )
    return result


@router.post("/disconnect")
async def telegram_disconnect(
    body: DisconnectRequest,
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Disconnect requires explicit confirmation")
    result = await _control("disconnect")
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_DISCONNECT,
        object_type="telegram_configuration",
        object_id="1",
        ip_address=ctx.ip_address,
    )
    return result


@router.post("/test")
async def telegram_test(
    ctx: AuthContext = Depends(require_operator),
    db: Session = Depends(get_db),
):
    cfg = db.get(TelegramConfiguration, 1)
    if cfg is None or cfg.status not in ("authorized", "reconnecting", "disconnected", "error"):
        raise HTTPException(status_code=409, detail="Telegram is not configured")
    # collector connectivity without changing monitored sources
    try:
        result = await _control("status")
    except HTTPException as e:
        log_audit(
            db,
            actor_user_id=ctx.user.id,
            actor_username=ctx.user.username,
            action=ACTION_TELEGRAM_CONNECT,
            object_type="telegram_configuration",
            object_id="1",
            detail={"test": "failed", "error": redact_text(str(e.detail))},
            ip_address=ctx.ip_address,
        )
        raise
    log_audit(
        db,
        actor_user_id=ctx.user.id,
        actor_username=ctx.user.username,
        action=ACTION_TELEGRAM_CONNECT,
        object_type="telegram_configuration",
        object_id="1",
        detail={"test": "ok", "state": result.get("state")},
        ip_address=ctx.ip_address,
    )
    return {"ok": result.get("state") == "authorized", "state": result.get("state")}
