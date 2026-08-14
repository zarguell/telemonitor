"""Overview dashboard aggregates (authenticated)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, AlertState, Message, MessageState, Severity, Source, TelegramConfiguration
from ..security import AuthContext, require_any

router = APIRouter(prefix="/overview", tags=["overview"])

SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


@router.get("")
def overview(ctx: AuthContext = Depends(require_any), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)

    tg = db.get(TelegramConfiguration, 1)
    enabled_sources = db.scalar(select(func.count(Source.id)).where(Source.enabled.is_(True))) or 0
    backfill_in_progress = db.scalar(
        select(func.count(Source.id)).where(Source.status == "backfilling")
    ) or 0
    messages_24h = db.scalar(select(func.count(Message.id)).where(Message.ingested_at >= day_ago)) or 0
    failed_messages_24h = db.scalar(
        select(func.count(Message.id)).where(
            Message.ingested_at >= day_ago, Message.state == MessageState.FAILED
        )
    ) or 0

    open_alerts = {
        sev: db.scalar(
            select(func.count(Alert.id)).where(
                Alert.state.in_([AlertState.OPEN, AlertState.ACKNOWLEDGED]),
                Alert.severity == sev,
            )
        )
        or 0
        for sev in SEVERITY_ORDER
    }

    recent_errors: list[dict] = []
    for src in db.scalars(
        select(Source).where(Source.last_error.is_not(None)).order_by(Source.updated_at.desc()).limit(5)
    ):
        recent_errors.append({"kind": "source", "source": src.title, "error": src.last_error})
    failed_alerts = db.scalars(
        select(Alert).where(Alert.delivery_state == "failed").order_by(Alert.updated_at.desc()).limit(5)
    ).all()
    for a in failed_alerts:
        recent_errors.append(
            {"kind": "alert_delivery", "alert_id": a.id, "error": a.last_delivery_error}
        )

    queue_stats = {}
    try:
        rows = db.execute(
            text(
                "SELECT queue_name, count(*) FILTER (WHERE status='todo') AS depth, "
                "count(*) FILTER (WHERE status='failed') AS failed "
                "FROM procrastinate_jobs GROUP BY queue_name"
            )
        ).mappings().all()
        queue_stats = {r["queue_name"]: {"depth": r["depth"], "failed": r["failed"]} for r in rows}
    except Exception:  # noqa: BLE001
        pass

    return {
        "telegram": {
            "state": tg.status if tg else "not_configured",
            "detail": tg.status_detail if tg else None,
            "collector_heartbeat": tg.collector_heartbeat_at.isoformat() if tg and tg.collector_heartbeat_at else None,
        },
        "enabled_sources": enabled_sources,
        "backfill_in_progress": backfill_in_progress,
        "messages_24h": messages_24h,
        "failed_messages_24h": failed_messages_24h,
        "open_alerts": open_alerts,
        "open_alert_total": sum(open_alerts.values()),
        "recent_errors": recent_errors,
        "queues": queue_stats,
    }
