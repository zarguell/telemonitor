"""Audit trail helper. Only sanitized details may be written."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, AppSetting, User

# Actions we audit
ACTION_LOGIN = "auth.login"
ACTION_LOGIN_FAILED = "auth.login_failed"
ACTION_LOGOUT = "auth.logout"
ACTION_TELEGRAM_INIT = "telegram.initialize"
ACTION_TELEGRAM_PHONE = "telegram.phone"
ACTION_TELEGRAM_CONNECT = "telegram.connect"
ACTION_TELEGRAM_DISCONNECT = "telegram.disconnect"
ACTION_TELEGRAM_CODE_SUBMITTED = "telegram.code_submitted"  # sanitized: no code value
ACTION_TELEGRAM_2FA_SUBMITTED = "telegram.2fa_submitted"  # sanitized: no password value
ACTION_SOURCE_ADD = "source.add"
ACTION_SOURCE_UPDATE = "source.update"
ACTION_SOURCE_DELETE = "source.delete"
ACTION_SOURCE_ENABLE = "source.enable"
ACTION_SOURCE_PAUSE = "source.pause"
ACTION_RULE_CREATE = "rule.create"
ACTION_RULE_UPDATE = "rule.update"
ACTION_RULE_DELETE = "rule.delete"
ACTION_RULE_TEST = "rule.test"
ACTION_SEARCH = "search.query"
ACTION_ALERT_TRIAGE = "alert.triage"
ACTION_SETTINGS_UPDATE = "settings.update"
ACTION_DESTINATION_TEST = "destination.test"
ACTION_USER_CREATE = "user.create"
ACTION_USER_UPDATE = "user.update"
ACTION_RETENTION_RUN = "retention.run"
ACTION_MAINTENANCE_RUN = "maintenance.run"

_ACTIONS = frozenset(
    [
        ACTION_LOGIN,
        ACTION_LOGIN_FAILED,
        ACTION_LOGOUT,
        ACTION_TELEGRAM_INIT,
        ACTION_TELEGRAM_PHONE,
        ACTION_TELEGRAM_CONNECT,
        ACTION_TELEGRAM_DISCONNECT,
        ACTION_TELEGRAM_CODE_SUBMITTED,
        ACTION_TELEGRAM_2FA_SUBMITTED,
        ACTION_SOURCE_ADD,
        ACTION_SOURCE_UPDATE,
        ACTION_SOURCE_DELETE,
        ACTION_SOURCE_ENABLE,
        ACTION_SOURCE_PAUSE,
        ACTION_RULE_CREATE,
        ACTION_RULE_UPDATE,
        ACTION_RULE_DELETE,
        ACTION_RULE_TEST,
        ACTION_SEARCH,
        ACTION_ALERT_TRIAGE,
        ACTION_SETTINGS_UPDATE,
        ACTION_DESTINATION_TEST,
        ACTION_USER_CREATE,
        ACTION_USER_UPDATE,
        ACTION_RETENTION_RUN,
        ACTION_MAINTENANCE_RUN,
    ]
)


def log_audit(
    db: Session,
    *,
    actor_user_id: int | None,
    actor_username: str | None,
    action: str,
    object_type: str | None = None,
    object_id: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    if action not in _ACTIONS:
        action = f"custom.{action}"
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        detail=detail or {},
        ip_address=ip_address,
    )
    db.add(event)
    db.commit()
    return event


def list_audit(
    db: Session,
    *,
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[AuditEvent], int]:
    q = select(AuditEvent)
    count_q = select(AuditEvent.id)
    if actor:
        q = q.where(AuditEvent.actor_username.ilike(f"%{actor}%"))
        count_q = count_q.where(AuditEvent.actor_username.ilike(f"%{actor}%"))
    if action:
        q = q.where(AuditEvent.action.ilike(f"%{action}%"))
        count_q = count_q.where(AuditEvent.action.ilike(f"%{action}%"))
    if object_type:
        q = q.where(AuditEvent.object_type == object_type)
        count_q = count_q.where(AuditEvent.object_type == object_type)
    if start:
        q = q.where(AuditEvent.created_at >= start)
        count_q = count_q.where(AuditEvent.created_at >= start)
    if end:
        q = q.where(AuditEvent.created_at <= end)
        count_q = count_q.where(AuditEvent.created_at <= end)
    total = db.scalar(count_q) or 0
    rows = list(
        db.scalars(q.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit))
    )
    return rows, total


def get_setting(db: Session, key: str, default=None):
    row = db.get(AppSetting, key)
    if row is None:
        return default
    return row.value


def set_setting(db: Session, key: str, value, updated_by: str | None = None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value, updated_by=updated_by)
        db.add(row)
    else:
        row.value = value
        row.updated_by = updated_by
    db.commit()


def ensure_seeded_settings(db: Session) -> None:
    """Seed default settings on first boot (retention days, destination)."""
    if get_setting(db, "retention_days") is None:
        from .config import settings as cfg

        set_setting(db, "retention_days", {"days": cfg.default_retention_days})
    if get_setting(db, "alert_destination") is None:
        set_setting(db, "alert_destination", {"type": "none"})
    if get_setting(db, "aliases") is None:
        set_setting(db, "aliases", {"items": []})


def get_retention_days(db: Session) -> int:
    val = get_setting(db, "retention_days", {})
    try:
        return max(0, int((val or {}).get("days", 90)))
    except (TypeError, ValueError):
        return 90
